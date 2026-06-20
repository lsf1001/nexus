"""测试 ws.py 在 chat 流程中 emit 4 个产品事件。

覆盖:
  - emit_chat_event 公开 API 能写入 sink
  - emit_chat_event 异常被吞掉(观测层不能影响主流程)
  - 4 个产品事件 dataclass 都能 round-trip 过 sink
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.backend.observability.events import (
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)
from nexus.backend.observability.sink import EventSink


@pytest.fixture
def jsonl_sink(tmp_path: Path) -> EventSink:
    sink = EventSink(path=tmp_path / "events.jsonl", format="json")
    yield sink
    sink.close()


def test_emit_chat_event_writes_to_sink(jsonl_sink: EventSink):
    """emit_chat_event 公开 API 应写到 sink。"""
    from nexus.backend.api import ws as ws_module

    with patch.object(ws_module, "_get_observability_sink", lambda: jsonl_sink):
        ws_module.emit_chat_event(
            ChatStart(
                timestamp="t",
                event="chat.start",
                session_id="s",
                message_id="m",
                content_len=3,
            )
        )

    lines = jsonl_sink._path.read_text().strip().split("\n")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "chat.start"
    assert payload["session_id"] == "s"


def test_emit_chat_event_swallows_exceptions(tmp_path: Path):
    """emit_chat_event 失败不抛(观测层不能影响主流程)。"""
    from nexus.backend.api import ws as ws_module

    def broken_sink() -> EventSink:
        raise RuntimeError("sink unavailable")

    with patch.object(ws_module, "_get_observability_sink", broken_sink):
        # 不应抛
        ws_module.emit_chat_event(
            ChatStart(
                timestamp="t",
                event="chat.start",
                session_id="s",
                message_id="m",
                content_len=1,
            )
        )


def test_event_dataclass_round_trips_through_sink(jsonl_sink: EventSink):
    """4 个产品事件 dataclass 都能 round-trip 过 sink。"""
    from nexus.backend.api import ws as ws_module

    with patch.object(ws_module, "_get_observability_sink", lambda: jsonl_sink):
        ws_module.emit_chat_event(
            ChatStart(
                timestamp="t1",
                event="chat.start",
                session_id="s1",
                message_id="m1",
                content_len=10,
            )
        )
        ws_module.emit_chat_event(
            IntentClassified(
                timestamp="t2",
                event="intent.classified",
                session_id="s1",
                message_id="m1",
                intent="chitchat",
                latency_ms=200,
            )
        )
        ws_module.emit_chat_event(
            QualityVerdict(
                timestamp="t3",
                event="quality.verdict",
                session_id="s1",
                message_id="m1",
                verdict="ACCEPT",
                scores={"safety": 0.9},
                repair_attempted=False,
            )
        )
        ws_module.emit_chat_event(
            ChatEnd(
                timestamp="t4",
                event="chat.end",
                session_id="s1",
                message_id="m1",
                chunks=12,
                duration_ms=1500,
                retry_count=0,
            )
        )

    lines = jsonl_sink._path.read_text().strip().split("\n")
    assert len(lines) == 4
    events = [json.loads(line)["event"] for line in lines]
    assert events == [
        "chat.start",
        "intent.classified",
        "quality.verdict",
        "chat.end",
    ]
