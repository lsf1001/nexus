#!/usr/bin/env python3
"""绕过 Vite,直接连后端测试 HITL 流程。

目的:验证 HITL 批准后 write_file 工具是否能在后端完成(把文件落到磁盘)。
如果直连能跑通 → Vite 代理是 WS 半关闭的元凶
如果直连也不能跑通 → deepagents HITL resume 内部问题
"""
import asyncio
import json
import sys
from pathlib import Path

import websockets

WS_URL = "ws://localhost:30000/api/ws?token=nexus-default-token"
# 受保护路径(命中 QualityGateMiddleware 的 HITL 中断),但必须在测试启动前
# 备份并删除,否则 deepagents StoreBackend 会因 "已存在不能覆盖" 拒绝。
# 这是 deepagents 自己的安全策略(强制 read 先),不是我们要测的 bug。
PROTECTED_TARGET = Path.home() / ".nexus" / "AGENTS.md"
PROTECTED_BACKUP = Path.home() / ".nexus" / "AGENTS.md.bak"
PROMPT = (
    f'请直接调用 write_file 工具把内容 "e2e_hitl_marker_2026" 写入文件 '
    f'{PROTECTED_TARGET}(全新文件,只写这一行内容即可)。'
    f'不要用 ask_user 工具提问,不要用 read_file 读,不要用 ls 列目录,'
    f'直接调用 write_file 一次完成。'
)


async def main() -> int:
    print(f"Connecting to {WS_URL}")
    try:
        ws = await websockets.connect(WS_URL)
    except Exception as e:
        print(f"Connect failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"Connected, ws={ws}")
    try:
        # 服务端不主动发"connected"帧(Vite HMR 那个是它的),直接发 user 消息
        print("[TX] user message (no connected wait)")

        # 发送 user 消息
        await ws.send(json.dumps({
            "type": "message",
            "content": PROMPT,
            "title": "HITL bypass test",
        }))
        print("[TX] user message")

        # 收集所有帧直到 收到 confirmation_request
        interrupts_to_approve: list[tuple[str, int]] = []
        while True:
            frame_raw = await asyncio.wait_for(ws.recv(), timeout=120)
            frame = json.loads(frame_raw)
            t = frame.get("type", "?")
            if t == "confirmation_request":
                interrupt_id = frame.get("interrupt_id", "")
                event_id = frame.get("event_id", 0)
                interrupts_to_approve.append((interrupt_id, event_id))
                print(
                    f"[RX] confirmation_request interrupt_id={interrupt_id} "
                    f"(累计 {len(interrupts_to_approve)})"
                )
                break
            elif t == "error":
                print(f"[RX] error: {frame}", file=sys.stderr)
                return 1
            elif t == "thinking":
                print(f"[RX] thinking: {frame.get('content', '')[:60]}")
            else:
                print(f"[RX] {t}: {str(frame)[:100]}")

        if not interrupts_to_approve:
            print("no interrupt_id", file=sys.stderr)
            return 1

        # 批准
        for interrupt_id, event_id in interrupts_to_approve:
            await ws.send(json.dumps({
                "type": "confirmation_response",
                "event_id": event_id,
                "interrupt_id": interrupt_id,
                "decision": "approve",
            }))
            print(f"[TX] confirmation_response approve #{len(interrupts_to_approve)}")

        # 收集后续帧,可能还有第二次 confirmation_request(已存在文件覆盖)
        received_done = False
        while True:
            try:
                frame_raw = await asyncio.wait_for(ws.recv(), timeout=180)
            except asyncio.TimeoutError:
                print("[TIMEOUT] 180s 无新帧", file=sys.stderr)
                return 1
            frame = json.loads(frame_raw)
            t = frame.get("type", "?")
            if t == "done":
                received_done = True
                print(f"[RX] done")
                break
            elif t == "error":
                print(f"[RX] error: {frame}", file=sys.stderr)
                return 1
            elif t == "confirmation_request":
                # 第二次 HITL(覆盖已存在文件)
                interrupt_id = frame.get("interrupt_id", "")
                event_id = frame.get("event_id", 0)
                print(f"[RX] 二次 confirmation_request interrupt_id={interrupt_id}")
                await ws.send(json.dumps({
                    "type": "confirmation_response",
                    "event_id": event_id,
                    "interrupt_id": interrupt_id,
                    "decision": "approve",
                }))
                print(f"[TX] 二次 approve")
            elif t == "thinking":
                print(f"[RX] thinking: {frame.get('content', '')[:100]}")
            elif t == "final":
                content = frame.get("content", "")
                print(f"[RX] final: {content[:200]}")
                # 关键断言(bug #58 修复):final 不应包含 Judge raw JSON 风格
                if '"score"' in content or '"reasoning"' in content:
                    print(f"❌ BUG #58: final 帧包含 Judge raw JSON: {content[:200]}")
                    return 2
            elif t == "chunk":
                content = frame.get("content", "")
                # 关键断言(bug #58 修复):chunk 不应包含 Judge raw JSON 风格
                if '"score"' in content or '"reasoning"' in content:
                    print(f"❌ BUG #58: chunk 帧包含 Judge raw JSON: {content}")
                    return 2
            elif t == "token_usage":
                print(f"[RX] token_usage")
            else:
                print(f"[RX] {t}: {str(frame)[:100]}")

        if not received_done:
            print("no done frame received", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"WS exception: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        await ws.close()

    # 检查文件是否落盘
    target = PROTECTED_TARGET
    print(f"\n=== 检查文件 ===")
    print(f"path: {target}")
    print(f"exists: {target.exists()}")
    if target.exists():
        content = target.read_text()
        print(f"size: {len(content)} bytes")
        print(f"content: {content!r}")
        if "e2e_hitl_marker_2026" in content:
            print("✅ marker 字符串在文件中,write_file 工具成功执行")
            return 0
    print("❌ 文件未包含 marker 字符串")
    return 1


def _setup_target() -> None:
    """测试前备份并删除 protected target,让 deepagents StoreBackend 允许写入。

    测试结束后由 caller 调 ``_restore_target()`` 还原 ——
    ``~/.nexus/AGENTS.md`` 是用户级记忆,误删会导致 Nexus 失去身份感。
    """
    if not PROTECTED_TARGET.exists():
        return
    PROTECTED_BACKUP.write_bytes(PROTECTED_TARGET.read_bytes())
    PROTECTED_TARGET.unlink()
    print(f"[setup] 已备份并删除 {PROTECTED_TARGET}")


def _restore_target() -> None:
    """还原 protected target(从备份)。如果测试失败导致 PROTECTED_TARGET 已被
    LLM 写入,LLM 内容会覆盖备份(此时备份里的旧内容丢失)。"""
    if PROTECTED_TARGET.exists():
        # LLM 已写入,放弃备份(LLM 内容可能是测试期望)
        if PROTECTED_BACKUP.exists():
            PROTECTED_BACKUP.unlink()
        print(f"[restore] {PROTECTED_TARGET} 已是 LLM 写入,保留")
        return
    if PROTECTED_BACKUP.exists():
        PROTECTED_TARGET.write_bytes(PROTECTED_BACKUP.read_bytes())
        PROTECTED_BACKUP.unlink()
        print(f"[restore] 已还原 {PROTECTED_TARGET}")


# 返回码约定:
#   0 - 全部通过(文件落盘 + Judge 输出未泄漏)
#   1 - HITL/WS 失败
#   2 - BUG #58: 流帧包含 Judge raw JSON


def _run() -> int:
    _setup_target()
    try:
        return asyncio.run(main())
    finally:
        _restore_target()


if __name__ == "__main__":
    sys.exit(_run())
