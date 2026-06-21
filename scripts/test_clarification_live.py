"""手动验证澄清链路的 ws 客户端脚本。

不依赖桌面 GUI。直接连 ws://localhost:30000/api/ws,
发消息,收集所有帧,打印结果。

运行:
    1. 启动后端:source .venv/bin/activate && uvicorn nexus.backend.main:app --port 30000
    2. 在另一个终端:python scripts/test_clarification_live.py "我想吃"

测试场景:
    - "我想吃"      → LLM 应该弹"想吃什么?"澄清卡片
    - "帮我处理一下"  → LLM 应该弹"处理什么?"澄清卡片
    - "我想吃火锅"   → LLM 应该直接回答,不需要澄清
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# 让脚本能找到 nexus 包
sys.path.insert(0, str(Path(__file__).parent.parent))

import websockets  # type: ignore[import-not-found]


async def collect_frames(message: str, token: str = "nexus-default-token") -> list[dict]:
    """连 ws,发消息,收集所有帧直到 done/clarification_request/error。"""
    url = f"ws://127.0.0.1:{os.environ.get('NEXUS_PORT', '30000')}/api/ws?token={token}"
    frames: list[dict] = []
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            await ws.send(json.dumps({"content": message, "title": "clarify-live-test"}))
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
                    frame = json.loads(raw)
                    frames.append(frame)
                    t = frame.get("type")
                    if t in {"done", "clarification_request", "error"}:
                        # done 后还会有关闭但不会再有业务帧;clarification_request 后挂起;
                        # error 后通常紧跟 done
                        if t in {"clarification_request", "error"}:
                            break
                        if t == "done":
                            break
            except TimeoutError:
                frames.append({"type": "TIMEOUT", "note": "60s 内没收到终止帧"})
    except Exception as exc:
        frames.append({"type": "CONNECT_FAIL", "error": str(exc)})
    return frames


def render_summary(frames: list[dict]) -> str:
    """把帧序列渲染成人能一眼看懂的报告。"""
    lines: list[str] = []
    lines.append(f"收到 {len(frames)} 帧")
    clarify = [f for f in frames if f.get("type") == "clarification_request"]
    chunks: list[str] = []
    thinking: list[str] = []
    has_final = has_done = has_error = False

    for f in frames:
        t = f.get("type")
        if t == "chunk":
            chunks.append(f.get("content", ""))
        elif t == "thinking":
            thinking.append(f.get("content", ""))
        elif t == "final":
            has_final = True
        elif t == "done":
            has_done = True
        elif t == "error":
            has_error = True

    # 状态判定
    if clarify:
        c = clarify[0]
        lines.append("✅ 触发澄清")
        lines.append(f"  问题: {c.get('content')}")
        opts = c.get("options") or []
        if opts:
            lines.append(f"  候选项 ({len(opts)}): {', '.join(opts)}")
        else:
            lines.append("  候选项: (空,用户自由输入)")
    elif has_error:
        err = next(f for f in frames if f.get("type") == "error")
        lines.append("❌ 后端报错")
        lines.append(f"  错误码: {err.get('error_code', '?')}")
        lines.append(f"  内容: {err.get('content', '?')}")
        lines.append(f"  可重试: {err.get('retryable', '?')}")
    elif chunks:
        lines.append("ℹ️  LLM 直接回复,没触发澄清")
        lines.append(f"  回复: {''.join(chunks)[:200]}")
    else:
        lines.append("⚠️  既没回复也没澄清,可能 agent 没启动")

    if thinking:
        for t in thinking[:5]:
            lines.append(f"  💭 {t[:150]}")

    if has_final:
        lines.append("  (收到 final 帧 — 流已结束)")
    if has_done:
        lines.append("  (收到 done 帧 — 流已结束)")
    return "\n".join(lines)


async def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/test_clarification_live.py <消息>")
        sys.exit(1)
    message = sys.argv[1]
    print(f"发送: {message!r}")
    print("---")
    frames = await collect_frames(message)
    print(render_summary(frames))
    print("---")
    print(f"完整帧数: {len(frames)},类型分布:")
    from collections import Counter

    cnt = Counter(f.get("type") for f in frames)
    for t, n in cnt.most_common():
        print(f"  {t}: {n}")


if __name__ == "__main__":
    asyncio.run(main())
