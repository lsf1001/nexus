"""测试 NexusLogHandler 把 LangChain LLM/tool/chain 事件落到 EventSink。"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from nexus.backend.observability.handler import NexusLogHandler
from nexus.backend.observability.sink import EventSink


def _make_sink(tmp_path: Path) -> EventSink:
    return EventSink(path=tmp_path / "events.jsonl", format="json")


def test_handler_subclasses_base_callback_handler():
    h = NexusLogHandler(sink=_make_sink(Path("/tmp")))
    assert isinstance(h, BaseCallbackHandler)


def test_on_llm_end_writes_event(tmp_path: Path):
    sink = _make_sink(tmp_path)
    h = NexusLogHandler(sink=sink)

    h.on_llm_start(serialized={"name": "ChatOpenAI"}, prompts=["hi"], run_id="r1")
    h.on_llm_end(
        response=LLMResult(generations=[[ChatGeneration(message=AIMessage(content="hi there"), text="hi there")]]),
        run_id="r1",
    )

    sink.close()
    lines = [ln for ln in (tmp_path / "events.jsonl").read_text().strip().split("\n") if ln]
    # 至少 on_llm_start + on_llm_end 两条
    assert len(lines) >= 2
    parsed = [json.loads(ln) for ln in lines]
    kinds = {p["event"] for p in parsed}
    assert "llm.start" in kinds
    assert "llm.end" in kinds


def test_on_tool_start_writes_event_with_tool_name(tmp_path: Path):
    sink = _make_sink(tmp_path)
    h = NexusLogHandler(sink=sink)
    h.on_tool_start(serialized={"name": "web_search"}, input_str="search query", run_id="r1")
    sink.close()

    lines = [json.loads(ln) for ln in (tmp_path / "events.jsonl").read_text().strip().split("\n") if ln]
    tool_starts = [p for p in lines if p["event"] == "tool.start"]
    assert len(tool_starts) == 1
    assert tool_starts[0]["tool"] == "web_search"


def test_sink_failure_does_not_break_callback_chain(tmp_path: Path):
    """EventSink 关闭后再 emit 不应抛异常(防止 callback 链中断)。"""
    sink = _make_sink(tmp_path)
    sink.close()  # 提前关掉
    h = NexusLogHandler(sink=sink)
    # 不应抛
    h.on_llm_start(serialized={"name": "ChatOpenAI"}, prompts=["hi"], run_id="r1")
