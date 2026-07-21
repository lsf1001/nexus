"""ask_user 强约束 E2E 探针:验证 LLM 在用户输入模糊时被 prompt 约束
  → 必须传 options(不是空数组 / 免责声明文本)。

覆盖:
  1. WS 鉴权 + 子协议
  2. 发歧义 prompt("我想吃" — 单动词,触发 ask_user)
  3. 验证收到 clarification_request 帧 + options 长度 >= 2
  4. 兜底:即使 LLM 仍传空 options,后端也会发 warning log
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time

import websockets

HOST = "localhost"
PORT = 30000
TOKEN = "e2e-clarify-2026"
SESSION_ID = "e2e_clarify_probe"


def make_subprotocol(token: str) -> str:
    b64 = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    return f"nxv1-{b64}"


async def main() -> int:
    subproto = make_subprotocol(TOKEN)
    print(f"[probe] token={TOKEN[:8]}... subproto={subproto[:24]}...")

    async with websockets.connect(f"ws://{HOST}:{PORT}/api/ws", subprotocols=[subproto]) as ws:
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=3.0)
            print(f"[probe] first frame: {first[:200]}")
        except TimeoutError:
            print("[probe] no initial frame (server is passive)")

        # 单字歧义指令:触发 ask_user 强约束
        prompt = "我想吃"
        await ws.send(json.dumps({"content": prompt, "session_id": SESSION_ID}))
        print(f"[probe] sent prompt: {prompt!r}")

        deadline = time.monotonic() + 180  # 真 LLM 慢一些
        all_frames: list[dict] = []
        clarification = None
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20.0)
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
            if ftype == "clarification_request":
                clarification = payload
                opts = payload.get("options") or []
                print(f"[OK] clarification_request: q={payload.get('content', '')[:60]!r}")
                print(f"     options count={len(opts)}, opts={opts!r}")
                break
            elif ftype == "final":
                final_content = payload.get("content", "")[:300]
                print(f"[INFO] final frame (LLM 没调 ask_user,直接答了): {final_content}")
                break
            elif ftype == "error":
                print(f"[FAIL] error frame: {payload}")
                return 1
            elif ftype in ("chunk", "thinking"):
                # 观测用:看到 LLM 在跑就行
                content_preview = payload.get("content", "")[:60]
                if ftype == "thinking" and content_preview:
                    print(f"  thinking: {content_preview!r}")
                continue
            else:
                print(f"  frame {ftype}: {str(payload)[:120]}")

        if clarification is None:
            print(f"[FAIL] no clarification_request in 90s; total frames={len(all_frames)}")
            for f in all_frames[-5:]:
                print(f"  {f.get('type')}: {str(f)[:120]}")
            return 1

        opts = clarification.get("options") or []
        if len(opts) >= 2:
            print(f"[PASS] options 满足强约束(>=2 个): {opts}")
            return 0
        elif len(opts) == 1:
            print(f"[WARN] options 只有 1 个(违反强约束): {opts}")
            return 1
        else:
            print(f"[FAIL] options 为空(违反强约束,前端会兜底): {opts}")
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
