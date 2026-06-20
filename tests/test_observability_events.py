"""测试 4 个产品事件的 dataclass schema 与 JSON 序列化。"""

from __future__ import annotations

import dataclasses
import json

from nexus.backend.observability.events import (
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)


def test_chat_start_to_dict_round_trip():
    e = ChatStart(
        timestamp="2026-06-20T14:00:00.000Z",
        event="chat.start",
        session_id="s-1",
        message_id="m-1",
        content_len=5,
    )
    d = e.to_dict()
    assert d["event"] == "chat.start"
    assert d["session_id"] == "s-1"
    assert d["content_len"] == 5
    # 必须可 JSON 序列化(线上 sink 写 JSONL)
    assert json.loads(json.dumps(d)) == d


def test_intent_classified_latency_ms_field():
    e = IntentClassified(
        timestamp="2026-06-20T14:00:00.200Z",
        event="intent.classified",
        session_id="s-1",
        message_id="m-1",
        intent="chitchat",
        latency_ms=200,
    )
    assert e.to_dict()["latency_ms"] == 200


def test_quality_verdict_carries_scores():
    e = QualityVerdict(
        timestamp="2026-06-20T14:00:01.000Z",
        event="quality.verdict",
        session_id="s-1",
        message_id="m-1",
        verdict="ACCEPT",
        scores={"safety": 0.95, "accuracy": 0.85},
        repair_attempted=False,
    )
    d = e.to_dict()
    assert d["verdict"] == "ACCEPT"
    assert d["scores"]["safety"] == 0.95
    assert d["repair_attempted"] is False


def test_chat_end_includes_duration_and_retries():
    e = ChatEnd(
        timestamp="2026-06-20T14:00:01.500Z",
        event="chat.end",
        session_id="s-1",
        message_id="m-1",
        chunks=12,
        duration_ms=1500,
        retry_count=0,
    )
    d = e.to_dict()
    assert d["chunks"] == 12
    assert d["duration_ms"] == 1500
    assert d["retry_count"] == 0


def test_events_are_frozen():
    e = ChatStart(timestamp="t", event="chat.start", session_id="s", message_id="m", content_len=1)
    try:
        e.session_id = "tamper"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError")
