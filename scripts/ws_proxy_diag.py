#!/usr/bin/env python3
"""诊断 Vite 代理 WS 是否半关闭:直连后端 vs 走 Vite 代理。

如果两条路径行为一致 → Vite 代理无 WS 半关闭问题
如果只有直连成功 → Vite proxy 配置需要修
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

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


async def _receive_until(ws, types, *, timeout=30) -> list[dict]:
    """收到任一 type 时返回所有收过的帧。"""
    frames: list[dict] = []
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        frame = json.loads(raw)
        frames.append(frame)
        if frame.get("type") in types:
            return frames


async def run(url: str, label: str) -> tuple[bool, str]:
    """发 1 条用户消息,等 confirmation_request 或 done。返回 (hitl_or_done, detail)。"""
    try:
        ws = await websockets.connect(url, open_timeout=5, close_timeout=2)
    except Exception as e:
        return False, f"connect fail: {type(e).__name__}: {e}"

    frames: list[dict] = []
    try:
        await ws.send(json.dumps({
            "type": "message",
            "content": PROMPT,
            "title": f"WS proxy diag ({label})",
        }))
        # 等 60s 收集帧
        frames = await _receive_until(
            ws, {"confirmation_request", "done", "error"}, timeout=60
        )
    except asyncio.TimeoutError:
        await ws.close()
        return False, "60s 无 confirmation_request / done / error"
    except Exception as e:
        await ws.close()
        return False, f"recv fail: {type(e).__name__}: {e}"
    finally:
        try:
            await ws.close()
        except Exception:
            pass

    types = [f.get("type") for f in frames]
    if "confirmation_request" in types:
        return True, f"got confirmation_request after {len(frames)} frames: {types[:8]}"
    if "done" in types:
        return True, f"got done (no HITL,可能 store 已存在?): {types[:8]}"
    if "error" in types:
        err = next((f for f in frames if f.get("type") == "error"), {})
        return False, f"got error: {err}"
    return False, f"unexpected end: {types[:8]}"


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
        print(f"=== 直连后端 ({WS_DIRECT}) ===")
        ok1, msg1 = await run(WS_DIRECT, "direct")
        print(("✅" if ok1 else "❌"), msg1)

        print(f"\n=== 走 Vite 代理 ({WS_PROXY}) ===")
        ok2, msg2 = await run(WS_PROXY, "vite")
        print(("✅" if ok2 else "❌"), msg2)

        print(f"\n=== 结论 ===")
        if ok1 and ok2:
            print("两条路径都成功,Vite 代理无 WS 半关闭问题。")
            return 0
        if ok1 and not ok2:
            print("Vite 代理 WS 半关闭!需要修 Vite proxy 配置。")
            return 2
        print("两条路径都失败,问题在别处。")
        return 1
    finally:
        _restore()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))