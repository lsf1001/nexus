"""回归测试:intent 分类前必须先发一个 thinking 心跳帧。

WHY:E2E 2026-06-28 用户切到 agnes 后 16 秒看不见任何反馈,
spinner 一直转。前端必须有"正在识别意图..."提示,才知道系统在干活。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nexus.backend import db


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test_heartbeat.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield str(db_path)
    monkeypatch.setattr(db, "_INITED", False)


class _FakeWebSocket:
    """最小可用的 WebSocket 替身:只记录 send_json 帧。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.frames.append(data)


class _SlowIntentLLM:
    """模拟慢 intent LLM(agnes 风格):ainvoke 阻塞 ~50ms。"""

    async def ainvoke(self, messages: list) -> Any:
        await asyncio.sleep(0.05)
        return type("R", (), {"tool_calls": [{"name": "route_chitchat"}]})()


@pytest.mark.asyncio
async def test_intent_heartbeat_emitted_before_classify(temp_db: str) -> None:
    """_classify_and_record 入口必须先发 thinking 心跳,再调 classify_intent。"""
    from nexus.backend.api.ws import _classify_and_record

    db.create_session("test-session", title="t", channel="main")

    ws = _FakeWebSocket()
    llm = _SlowIntentLLM()

    def get_intent_llm() -> Any:
        return llm

    await _classify_and_record(ws, get_intent_llm, "test-session", "hi")

    # 第一帧必须是 thinking 心跳
    assert ws.frames, "应该有心跳帧"
    assert ws.frames[0]["type"] == "thinking", f"第一帧不是 thinking: {ws.frames[0]}"
    content = ws.frames[0].get("content", "")
    assert "意图" in content or "识别" in content, f"thinking 内容应含意图/识别关键字: {content}"


@pytest.mark.asyncio
async def test_intent_heartbeat_emitted_even_when_llm_none(temp_db: str) -> None:
    """llm=None 时(早期 startup 场景)也要先发心跳,再兜底 chitchat。"""
    from nexus.backend.api.ws import _classify_and_record

    db.create_session("test-session2", title="t", channel="main")

    ws = _FakeWebSocket()

    await _classify_and_record(ws, lambda: None, "test-session2", "hi")

    first = ws.frames[0]
    assert first["type"] == "thinking"
    assert "意图" in first["content"] or "识别" in first["content"]
    assert first["event_id"] == 1  # default last_event_id=0 → heartbeat event_id=1


@pytest.mark.asyncio
async def test_intent_heartbeat_event_id_monotonic_with_last_event_id(temp_db: str) -> None:
    """心跳 event_id 必须 = last_event_id + 1,保证客户端 resume token 单调。

    WHY:这是整个改动最关键的契约。客户端用 last_event_id 续传,
    心跳若不参与单调序列,客户端可能错过续传点。
    """
    from nexus.backend.api.ws import _classify_and_record

    db.create_session("test-session3", title="t", channel="main")

    ws = _FakeWebSocket()

    # 传 last_event_id=42,心跳应当 event_id=43
    await _classify_and_record(ws, lambda: None, "test-session3", "hi", last_event_id=42)

    assert ws.frames[0]["type"] == "thinking"
    assert ws.frames[0]["event_id"] == 43
