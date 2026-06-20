"""测试 EventSink 的 JSONL 持久化、text stdout、轮转、并发写锁。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from nexus.backend.observability.events import ChatEnd, ChatStart
from nexus.backend.observability.sink import EventSink


def test_jsonl_write_creates_file_and_appends(tmp_path: Path):
    log_file = tmp_path / "events.jsonl"
    sink = EventSink(path=log_file, format="json")
    sink.emit(ChatStart(timestamp="t1", event="chat.start", session_id="s", message_id="m", content_len=1))
    sink.emit(
        ChatEnd(
            timestamp="t2", event="chat.end", session_id="s", message_id="m", chunks=2, duration_ms=100, retry_count=0
        )
    )
    sink.close()

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "chat.start"
    assert json.loads(lines[1])["event"] == "chat.end"


def test_text_format_writes_human_readable_to_file(tmp_path: Path):
    log_file = tmp_path / "events.log"
    sink = EventSink(path=log_file, format="text")
    sink.emit(
        ChatStart(timestamp="2026-06-20T14:00:00Z", event="chat.start", session_id="s", message_id="m", content_len=5)
    )
    sink.close()

    content = log_file.read_text(encoding="utf-8")
    assert "[chat.start]" in content
    assert "session_id=s" in content
    assert "content_len=5" in content
    # text 模式不应包含 JSON braces
    assert "{" not in content


def test_sink_creates_parent_directory(tmp_path: Path):
    log_file = tmp_path / "subdir" / "deep" / "events.jsonl"
    sink = EventSink(path=log_file, format="json")
    sink.emit(ChatStart(timestamp="t", event="chat.start", session_id="s", message_id="m", content_len=1))
    sink.close()
    assert log_file.exists()


def test_concurrent_writes_are_thread_safe(tmp_path: Path):
    """多线程并发 emit 不应交错同一行。"""
    log_file = tmp_path / "events.jsonl"
    sink = EventSink(path=log_file, format="json")

    def worker(i: int) -> None:
        for j in range(50):
            sink.emit(
                ChatStart(
                    timestamp=f"t-{i}-{j}",
                    event="chat.start",
                    session_id=f"s-{i}",
                    message_id=f"m-{i}-{j}",
                    content_len=j,
                )
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sink.close()

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 200
    # 每行必须能独立 JSON parse(没交错)
    for line in lines:
        json.loads(line)


def test_sink_close_is_idempotent(tmp_path: Path):
    log_file = tmp_path / "events.jsonl"
    sink = EventSink(path=log_file, format="json")
    sink.close()
    sink.close()  # 不应抛异常
