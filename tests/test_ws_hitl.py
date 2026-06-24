"""WS 层 HITL 桥接测试。

覆盖:
  - _serialize_hitl_request:把 langchain HumanInTheLoopMiddleware 标准
    ``hitl_request`` payload 转 WS ``confirmation_request`` 帧。
  - _run_agent_streaming:捕获 ``GraphInterrupt`` 后发 confirmation_request
    + 写入 pending state + 返回 ``pending_interrupts`` 元组。
  - handle_websocket:``confirmation_response`` 帧走 ``Command(resume=...)``
    续流(pending2 再次出现时回到挂起)。

WHY:plan Task 4 假设 ``astream_events`` yield interrupt 事件,但实测
deepagents 0.x / langgraph 的 HITL 抛 ``GraphInterrupt``(
``langgraph/errors.py:102``,继承 ``GraphBubbleUp``)。StreamGuard
默认 ``except Exception`` 会把 GraphInterrupt 当 unknown error 吞掉,
HITL 永远到不了前端。本测试守住"HITL 抛异常 → 前端收 confirmation_request"
这条关键不变量。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def test_serialize_hitl_request_write_file() -> None:
    """把 langchain HITL 标准 hitl_request payload 转 WS confirmation_request 帧。"""
    from nexus.backend.api.ws import _serialize_hitl_request

    # langchain HumanInTheLoopMiddleware 的标准 hitl_request 格式:
    # {"action_requests": [{"name": "write_file", "args": {...}, "description": "..."}, ...],
    #  "review_configs": {...}}
    hitl_request = {
        "action_requests": [
            {
                "name": "write_file",
                "args": {"file_path": "/tmp/proj/nexus/foo.py", "content": "print('hi')"},
                "description": "写入 nexus/foo.py",
            }
        ],
        "review_configs": {},
    }
    frame = _serialize_hitl_request(hitl_request, interrupt_id="hitl-1", event_id=42)
    assert frame["type"] == "confirmation_request"
    assert frame["event_id"] == 42
    assert frame["interrupt_id"] == "hitl-1"
    assert frame["actions"][0]["tool_name"] == "write_file"
    assert frame["actions"][0]["target_path"] == "/tmp/proj/nexus/foo.py"
    assert {a["decision"] for a in frame["actions"][0]["options"]} >= {"approve", "reject"}


def test_serialize_hitl_request_edit_file_preview_truncated() -> None:
    """edit_file 的新内容预览截断到 200 字。"""
    from nexus.backend.api.ws import _serialize_hitl_request

    long_content = "x" * 500
    hitl_request = {
        "action_requests": [
            {
                "name": "edit_file",
                "args": {"file_path": "/tmp/proj/README.md", "new_string": long_content},
                "description": "编辑 README.md",
            }
        ],
        "review_configs": {},
    }
    frame = _serialize_hitl_request(hitl_request, interrupt_id="x", event_id=1)
    preview = frame["actions"][0]["preview"]
    assert len(preview) <= 203  # 200 + "..."
    assert preview.endswith("...")


@pytest.mark.asyncio
async def test_run_agent_streaming_catches_graph_interrupt() -> None:
    """_run_agent_streaming 捕获 GraphInterrupt 并发 confirmation_request。

    WHY:deepagents HITL 路径在 ``astream_events`` 内部抛
    ``GraphInterrupt(interrupts=[Interrupt(value=hitl_request, id=...)])``
    而不是 yield 事件。``_run_agent_streaming`` 必须把这条异常翻译成
    ``confirmation_request`` 帧 + 把 ``pending_interrupts`` 元组返回,
    让 ``handle_websocket`` 据此挂起本轮流。
    """
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Interrupt

    from nexus.backend.api import ws

    hitl_request = {
        "action_requests": [{"name": "write_file", "args": {"file_path": "/tmp/proj/.nexus/AGENTS.md", "content": "x"}}]
    }
    interrupt = Interrupt(value=hitl_request, id="hitl-abc")
    graph_interrupt = GraphInterrupt(interrupts=[interrupt])

    async def fake_astream_events(*args, **kwargs):
        raise graph_interrupt
        yield  # pragma: no cover - 让它成为 async generator(实际不会执行到)

    mock_agent = MagicMock()
    mock_agent.astream_events = fake_astream_events
    mock_agent._nexus_log_handler = None
    mock_agent._nexus_verbose_handler = None

    mock_ws = AsyncMock()
    prompt = {"messages": []}

    last_id, response_text, completed, clarification, pending = await ws._run_agent_streaming(
        mock_ws, "sess-1", prompt, mock_agent
    )

    # 验证:发了一个 confirmation_request 帧
    assert mock_ws.send_json.call_count == 1
    sent_frame = mock_ws.send_json.call_args[0][0]
    assert sent_frame["type"] == "confirmation_request"
    assert sent_frame["interrupt_id"] == "hitl-abc"

    # 验证:返回值标记挂起
    assert completed is False
    assert response_text == ""
    assert clarification is None
    assert pending is not None
    assert len(pending) == 1
    assert pending[0].id == "hitl-abc"

    # 验证:pending state 已写入 _session_hitl_state(供 confirmation_response 续流用)
    state = ws._session_hitl_state.get("sess-1")
    assert state is not None
    assert state["thread_id"] == "sess-1"
    assert len(state["pending_interrupts"]) == 1
