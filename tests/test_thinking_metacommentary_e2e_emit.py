"""端到端:模拟用户截图里 LLM 真实 thinking 串,验证 emit 阶段 strip 行为。

为什么这里用 in-process asyncio 跑 _emit_chunks 而不是 e2e mock LLM:
- e2e mock 主要做 tool_calls 场景,不模拟纯 chat 直答
- 我们的目标是验证 _emit_chunks 的 strip 行为,只需要喂 raw thinking
  文本进 parser 流水线,不需要真 LLM
"""

from __future__ import annotations

import asyncio
from typing import Any

from nexus.backend.api.thinking_parser import ThinkingParser
from nexus.backend.api.ws.streaming import _emit_chunks


class _FakeWebSocket:
    """最小 WebSocket mock —— 只记录 send_json 调用,便于断言。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


def test_emit_strips_metacommentary_from_thinking_frame() -> None:
    """模拟用户截图里 LLM 真实 thinking 串,emit 阶段 strip 元话语。

    模拟场景(2026-07-14 用户反馈):
      LLM 输出:
        <thinking>The user is asking me to generate a koi image.
        I should be honest about this limitation.
        Looking at my available tools, I don't see any image gen tool.
        So I cannot actually generate an image. I should respond honestly and helpfully.
        Let me organize the response first acknowledge, then alternatives.</thinking>
        老白你好,我得跟你坦白一下...
    """
    parser = ThinkingParser()
    counter: dict[str, Any] = {
        "event_id": 0,
        "last_event_id": 0,
        "emitted_chunk_text": "",
    }
    ws = _FakeWebSocket()

    raw = (
        "<thinking>"
        "The user is asking me to generate a koi image.\n"
        "I should be honest about this limitation.\n"
        "Looking at my available tools, I don't see any image gen tool.\n"
        "So I cannot actually generate an image. I should respond honestly and helpfully.\n"
        "Let me organize the response first acknowledge, then alternatives."
        "</thinking>"
        "老白你好,我得跟你坦白一下:我没有图像生成能力。"
    )

    asyncio.run(_emit_chunks(ws, parser, raw, counter))

    # 至少 2 帧(1 thinking + 1 chunk)
    assert len(ws.sent) >= 2

    thinking_frame = ws.sent[0]
    assert thinking_frame["type"] == "thinking"
    thinking_content = thinking_frame["content"]
    # 元话语全 strip 干净
    assert "I should" not in thinking_content
    assert "Let me" not in thinking_content
    assert "Let me organize" not in thinking_content
    # 真推理保留
    assert "The user is asking" in thinking_content
    assert "Looking at my available tools" in thinking_content
    assert "I don't see any image gen" in thinking_content

    # 正文 chunk 不被 strip
    chunk_frame = ws.sent[1]
    assert chunk_frame["type"] == "chunk"
    assert "老白你好" in chunk_frame["content"]

    # emitted_chunk_text 累积的是 chunk 全文(包含正文),跟 emit 解耦
    assert "老白你好" in counter["emitted_chunk_text"]
    # 注意:DB 入库的是 emitted_chunk_text,完整正文保留
    # thinking_content 字段是另外从 thinking 帧里积累的,跟本函数无关


def test_emit_skips_fully_stripped_thinking_frame() -> None:
    """整个 thinking 块全由元话语组成 → 整帧 skip,不 send 给前端。"""
    parser = ThinkingParser()
    counter: dict[str, Any] = {
        "event_id": 0,
        "last_event_id": 0,
        "emitted_chunk_text": "",
    }
    ws = _FakeWebSocket()

    raw = "<thinking>I should be honest. I will acknowledge first. Let me organize.</thinking>答案是 A"
    asyncio.run(_emit_chunks(ws, parser, raw, counter))

    # thinking 帧被 strip 全空,跳过;只剩 1 帧 chunk
    sent_types = [frame["type"] for frame in ws.sent]
    assert sent_types == ["chunk"]
    assert ws.sent[0]["content"] == "答案是 A"


def test_emit_chunk_frame_untouched() -> None:
    """chunk 帧(非 thinking)不被 strip —— 即使用户正文里碰巧有 'I should'。"""
    parser = ThinkingParser()
    counter: dict[str, Any] = {
        "event_id": 0,
        "last_event_id": 0,
        "emitted_chunk_text": "",
    }
    ws = _FakeWebSocket()

    raw = "I should be honest about this limitation."  # 全是 chunk
    asyncio.run(_emit_chunks(ws, parser, raw, counter))

    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "chunk"
    assert ws.sent[0]["content"] == "I should be honest about this limitation."
    assert "I should" in counter["emitted_chunk_text"]  # 正文 100% 保留
