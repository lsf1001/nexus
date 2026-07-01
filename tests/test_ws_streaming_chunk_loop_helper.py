"""验证 _emit_chunks helper 在三种调用点(parser.feed / feed(end_content) / flush)
产出一致的 event_id + last_event_id 行为。"""

from __future__ import annotations

import asyncio
from typing import Any


class _StubWebSocket:
    """最小可用的 WS,只记录 send_json 调用。"""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)


class _StubParser:
    """Thought: feed / flush 都返回 ``[(kind, text), ...]``。"""

    def __init__(self, chunks: list[tuple[str, str]]) -> None:
        self._chunks = chunks
        self.feed_calls: list[str | None] = []
        self.flush_calls: int = 0

    def feed(self, text: str) -> list[tuple[str, str]]:
        self.feed_calls.append(text)
        return self._chunks

    def flush(self) -> list[tuple[str, str]]:
        self.flush_calls += 1
        return self._chunks


def _run(coro: Any) -> None:
    asyncio.run(coro)


def test_emit_chunks_three_sources_consistent_event_ids() -> None:
    """三种调用点 (feed / feed / flush) 产出单调递增且唯一的 event_id。"""
    from nexus.backend.api.ws.streaming import _emit_chunks

    ws = _StubWebSocket()
    parser = _StubParser([("chunk", "abc"), ("thinking", "x")])

    counter = {"event_id": 0, "last_event_id": 0, "emitted_chunk_text": ""}

    async def _go() -> None:
        # 三种调用点
        await _emit_chunks(ws, parser, "feed-arg-1", counter)
        await _emit_chunks(ws, parser, "feed-arg-2", counter)
        await _emit_chunks(ws, parser, None, counter, flush=True)

    _run(_go())

    # 6 帧发出 (3 调用点 × 2 chunk)
    assert len(ws.frames) == 6
    event_ids = [f["event_id"] for f in ws.frames]
    # event_id 单调 +1
    assert event_ids == sorted(event_ids)
    assert len(set(event_ids)) == 6, "event_id 必须唯一"
    # last_event_id 追上最大 event_id
    assert counter["last_event_id"] == max(event_ids)
    # emitted_chunk_text 累积所有 chunk text(3 调用点都含 "abc" chunk 帧)
    assert counter["emitted_chunk_text"] == "abcabcabc"


def test_emit_chunks_feed_only_routes_correctly() -> None:
    """feed 分支(flush=False)走 parser.feed(text) 而不是 parser.flush()。"""
    from nexus.backend.api.ws.streaming import _emit_chunks

    ws = _StubWebSocket()
    parser = _StubParser([("chunk", "y")])
    counter = {"event_id": 0, "last_event_id": 0, "emitted_chunk_text": ""}

    async def _go() -> None:
        await _emit_chunks(ws, parser, "hello", counter)

    _run(_go())
    assert parser.feed_calls == ["hello"]
    assert parser.flush_calls == 0


def test_emit_chunks_flush_only_routes_correctly() -> None:
    """flush 分支走 parser.flush() 而不是 parser.feed(text)。"""
    from nexus.backend.api.ws.streaming import _emit_chunks

    ws = _StubWebSocket()
    parser = _StubParser([("chunk", "z")])
    counter = {"event_id": 0, "last_event_id": 0, "emitted_chunk_text": ""}

    async def _go() -> None:
        await _emit_chunks(ws, parser, "ignored", counter, flush=True)

    _run(_go())
    assert parser.flush_calls == 1
    assert parser.feed_calls == []  # flush 分支不调 feed


def test_emit_chunks_only_chunk_kinds_accumulate_text() -> None:
    """emitted_chunk_text 只累加 kind=='chunk' 的 text,thinking 跳过。"""
    from nexus.backend.api.ws.streaming import _emit_chunks

    ws = _StubWebSocket()
    parser = _StubParser([("thinking", "thought1"), ("chunk", "real1"), ("thinking", "thought2"), ("chunk", "real2")])
    counter = {"event_id": 0, "last_event_id": 0, "emitted_chunk_text": ""}

    async def _go() -> None:
        await _emit_chunks(ws, parser, "text", counter)

    _run(_go())
    assert counter["emitted_chunk_text"] == "real1real2"


def test_emit_chunks_passes_through_none_text_when_not_flushing() -> None:
    """边界:text=None 且 flush=False 时仍调 parser.feed("")(空字符串兜底)。"""
    from nexus.backend.api.ws.streaming import _emit_chunks

    ws = _StubWebSocket()
    parser = _StubParser([("chunk", "ok")])
    counter = {"event_id": 0, "last_event_id": 0, "emitted_chunk_text": ""}

    async def _go() -> None:
        await _emit_chunks(ws, parser, None, counter)  # text=None, flush=False

    _run(_go())
    assert parser.feed_calls == [""]  # None 被兜底成 ""
