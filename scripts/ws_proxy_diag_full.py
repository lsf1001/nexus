#!/usr/bin/env python3
"""深度 WS proxy 诊断:完整 HITL 旅程(approval → done)对比直连 vs Vite。

bug #57 完整重现:HITL 批准后,直连走通 done,Vite 代理是否也能走通?
"""
import asyncio
import json
import sys
from pathlib import Path

import websockets

WS_DIRECT = "ws://localhost:30000/api/ws?token=nexus-default-token"
WS_PROXY = "ws://localhost:30077/api/ws?token=nexus-default-token"
PROMPT = (
    '请直接调用 write_file 工具把内容 "e2e_ws_proxy_diag" 写入文件 '
    '~/.nexus/AGENTS.md(覆盖整个文件,只写这一行内容即可)。'
    '不要用 ask_user 工具提问,直接调用 write_file 一次完成。'
)
PROTECTED_TARGET = Path.home() / ".nexus" / "AGENTS.md"
PROTECTED_BACKUP = Path.home() / ".nexus" / "AGENTS.md.bak"


async def run_full_hil(url: str, label: str) -> tuple[bool, str]:
    """完整 HITL 旅程,看 done 帧能不能收到。"""
    try:
        ws = await websockets.connect(url, open_timeout=5, close_timeout=2)
    except Exception as e:
        return False, f"connect fail: {type(e).__name__}: {e}"

    try:
        await ws.send(json.dumps({
            "type": "message",
            "content": PROMPT,
            "title": f"WS proxy diag ({label})",
        }))
        # 等 confirmation_request
        interrupt_id = None
        event_id = 0
        for _ in range(60):
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            frame = json.loads(raw)
            t = frame.get("type")
            if t == "confirmation_request":
                interrupt_id = frame.get("interrupt_id")
                event_id = frame.get("event_id")
                break
            if t == "error":
                return False, f"got error before HITL: {frame}"
        if not interrupt_id:
            return False, "no confirmation_request"

        # 立即 approve
        await ws.send(json.dumps({
            "type": "confirmation_response",
            "event_id": event_id,
            "interrupt_id": interrupt_id,
            "decision": "approve",
        }))

        # 等 done (180s 上限)
        for _ in range(180):
            raw = await asyncio.wait_for(ws.recv(), timeout=180)
            frame = json.loads(raw)
            t = frame.get("type")
            if t == "done":
                return True, f"got done after approval ({label})"
            if t == "error":
                return False, f"got error after approval: {frame}"
        return False, "timeout, no done"
    except asyncio.TimeoutError:
        return False, "timeout"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            await ws.close()
        except Exception:
            pass


def _setup() -> None:
    if PROTECTED_TARGET.exists():
        PROTECTED_BACKUP.write_bytes(PROTECTED_TARGET.read_bytes())
        PROTECTED_TARGET.unlink()


def _restore() -> None:
    if PROTECTED_TARGET.exists():
        if PROTECTED_BACKUP.exists():
            PROTECTED_BACKUP.unlink()
        return
    if PROTECTED_BACKUP.exists():
        PROTECTED_TARGET.write_bytes(PROTECTED_BACKUP.read_bytes())
        PROTECTED_BACKUP.unlink()


async def _main() -> int:
    _setup()
    try:
        print(f"=== 直连 ({WS_DIRECT}) ===")
        ok1, msg1 = await run_full_hil(WS_DIRECT, "direct")
        print(("✅" if ok1 else "❌"), msg1)

        print(f"\n=== 走 Vite ({WS_PROXY}) ===")
        ok2, msg2 = await run_full_hil(WS_PROXY, "vite")
        print(("✅" if ok2 else "❌"), msg2)

        print(f"\n=== 结论 ===")
        if ok1 and ok2:
            print("两条路径都成功(批准后 done 帧能收到)")
            return 0
        if ok1 and not ok2:
            print("Vite 代理 WS 半关闭:approval 后连接挂掉")
            return 2
        if not ok1 and ok2:
            print("直连失败,反而 Vite 通 — 不寻常")
            return 3
        print("两条路径都失败")
        return 1
    finally:
        _restore()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))