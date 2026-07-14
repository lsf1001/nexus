"""DMG 端到端探针:验证 ``shell_run`` 工具已嵌入并可被 LLM 调用。

覆盖链路:
  1. WS 鉴权通过(subprotocol ``nxv1-<base64url(token)>``)
  2. 发用户消息 → 后端代理到 LLM → LLM 调 ``shell_run`` →
     ``ShellHITLMiddleware`` 拦截 → 下发 ``confirmation_request`` 帧
  3. 自动 approve → ``shell_run`` 真正执行 ``ls ~/.nexus/outputs/`` →
     下发 ``final`` 帧(含 stdout)
  4. ``~/.nexus/logs/shell_executions.log`` 写入 ``decision=approve`` 行

退出码:
  0 = 全过;1 = 任何一步失败。

WHY 直连 WS(而非 Playwright/headless):
  DMG 已经在跑、后端 WS 已就绪。直连 WS 比启 headless 浏览器更轻、
  更可靠 — HITL 帧在后端 finalize 阶段就被序列化下发,直接拦截
  即可,免去前端渲染/确认卡的不确定性。
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import websockets

HOST = "localhost"
PORT = 30000
TOKEN_PATH = Path("/Users/yxb/projects/nexus/desktop/src-tauri/.build_token")
AUDIT_LOG = Path.home() / ".nexus" / "logs" / "shell_executions.log"
SESSION_ID = "e2e_shell_probe"


def make_subprotocol(token: str) -> str:
    """``nxv1-<base64url(token)>``(2026-07-12 重构后的协议格式)。"""
    b64 = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    return f"nxv1-{b64}"


async def main() -> int:
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    subproto = make_subprotocol(token)
    print(f"[probe] token={token[:8]}... subproto={subproto[:24]}...")

    async with websockets.connect(f"ws://{HOST}:{PORT}/api/ws", subprotocols=[subproto]) as ws:
        # 收首条 session_created / welcome 帧(后端可能在 ws accept 时主动发)
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=3.0)
            print(f"[probe] first frame: {first[:200]}")
        except TimeoutError:
            print("[probe] no initial frame (server is passive)")

        # 发用户消息(WS 入站消息不带 type,直接 content 字段)
        # WHY 强制 "调用 shell_run":LLM 看到 ~/.nexus/outputs/ 已有内容
        # 可能直接基于历史推断不调工具。用 "用 shell_run 工具,返回 stdout"
        # 强制工具调用。
        prompt = (
            "请你调用 shell_run 工具执行命令 'echo shell_run_e2e_$(date +%s)' "
            "把 stdout 完整返回给我,cwd 设为 ~/.nexus/outputs。"
        )
        await ws.send(
            json.dumps(
                {
                    "content": prompt,
                    "session_id": SESSION_ID,
                }
            )
        )
        print("[probe] sent user prompt")

        # 收集接下来 N 秒的帧
        deadline = time.monotonic() + 90
        got_hitl = False
        all_frames: list[dict] = []
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            except TimeoutError:
                print("[probe] recv timeout, breaking")
                break
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[probe] non-JSON frame: {raw[:200]}")
                continue
            all_frames.append(payload)
            ftype = payload.get("type")
            if ftype == "confirmation_request":
                got_hitl = True
                interrupt_id = payload.get("interrupt_id")
                event_id = payload.get("event_id")
                actions = payload.get("actions", [])
                print(f"[OK] HITL frame interrupt_id={interrupt_id} event_id={event_id}")
                for a in actions:
                    print(f"     action tool_name={a.get('tool_name')} target={a.get('target_path')}")
                # 自动 approve,看完整链路
                await ws.send(
                    json.dumps(
                        {
                            "type": "confirmation_response",
                            "interrupt_id": interrupt_id,
                            "event_id": event_id,
                            "decision": "approve",
                        }
                    )
                )
                print("[probe] auto-approved HITL")
            elif ftype == "final":
                final_content = payload.get("content", "")[:300]
                print(f"[OK] final frame: {final_content}")
                break
            elif ftype == "error":
                print(f"[FAIL] error frame: {payload}")
                return 1
            elif ftype == "chunk":
                pass  # 跳过思考/流式 chunk
            else:
                print(f"  frame {ftype}: {json.dumps(payload, ensure_ascii=False)[:120]}")

        if not got_hitl:
            print(f"[FAIL] no confirmation_request frame; total frames={len(all_frames)}")
            for f in all_frames[-5:]:
                print(f"  {f}")
            return 1

        # 审计日志验证(给日志 1 秒落盘时间)
        await asyncio.sleep(1.0)
        if not AUDIT_LOG.exists():
            print(f"[FAIL] audit log not at {AUDIT_LOG}")
            return 1
        lines = AUDIT_LOG.read_text(encoding="utf-8").strip().splitlines()
        # 找最近一条 approve(可能是这次 HITL approve 的)
        recent = [json.loads(line) for line in lines[-10:]]
        approved_recent = [r for r in recent if r.get("decision") == "approve"]
        if not approved_recent:
            print(f"[FAIL] no approve record in recent audit: {recent}")
            return 1
        last = approved_recent[-1]
        print(f"[OK] audit: decision={last.get('decision')} cmd={last.get('command')!r} exit={last.get('exit_code')}")
        if last.get("exit_code") != 0:
            print(f"[WARN] non-zero exit: {last}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
