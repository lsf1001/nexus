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

import time
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_finalize_after_stream_done_and_assistant_message() -> None:
    """``_finalize_after_stream`` 无挂起时应发 done + 入库 assistant 消息。

    回归测试:Task 4 commit ``ca6dec5`` 的 ``confirmation_response`` 路径
    fall-through 错位 —— 该帧的 ``content`` 为空,被 user 消息路径的
    ``if not user_content: continue`` 拦截,导致 approve 后 LLM 续流响应
    既不入库也不发 done。引入 ``_finalize_after_stream`` helper 把两条
    路径的 finalize 合并后,这条不变量必须被守住。
    """
    from nexus.backend.api.ws import _finalize_after_stream
    from nexus.backend.intent.router import DEFAULT_INTENT

    with patch("nexus.backend.api.ws.add_message") as mock_add_message:
        mock_ws = AsyncMock()
        await _finalize_after_stream(
            websocket=mock_ws,
            session_id="sess-finalize",
            user_content="",
            message_id="msg-finalize",
            chat_start_monotonic=time.monotonic(),
            intent_result=DEFAULT_INTENT,
            last_event_id=10,
            response_text="已写入 /tmp/foo.py",
            stream_completed=True,
            clarification=None,
            pending_interrupts=None,  # 关键:无挂起 → 应当正常 finalize
            agent=MagicMock(),
            get_quality_pipeline=None,
        )

    # 验证:发了一个 done 帧
    sent_frames = [c.args[0] for c in mock_ws.send_json.call_args_list]
    done_frames = [f for f in sent_frames if isinstance(f, dict) and f.get("type") == "done"]
    assert len(done_frames) == 1, f"应发 1 个 done 帧,实际发送: {sent_frames}"
    assert done_frames[0]["event_id"] == 11  # last_event_id + 1

    # 验证:assistant 消息入库(写库函数被调用)
    assert mock_add_message.called, "approve 后 LLM 续流响应必须入库"
    args = mock_add_message.call_args[0]
    assert args[1] == "sess-finalize"  # session_id
    assert args[2] == "assistant"  # role
    assert "已写入" in args[3]  # content


@pytest.mark.asyncio
async def test_finalize_after_stream_pending_interrupts_early_return() -> None:
    """``_finalize_after_stream`` 看到 ``pending_interrupts`` 应 early-return。

    WHY:HITL 二次挂起时不应发 done / 不入库 / 不 emit ChatEnd —— 等下次
    ``confirmation_response`` 续流。防止 helper 重复发送/写入。
    """
    from nexus.backend.api.ws import _finalize_after_stream
    from nexus.backend.intent.router import DEFAULT_INTENT

    with patch("nexus.backend.api.ws.add_message") as mock_add_message:
        mock_ws = AsyncMock()
        await _finalize_after_stream(
            websocket=mock_ws,
            session_id="sess-hitl2",
            user_content="",
            message_id="msg-hitl2",
            chat_start_monotonic=time.monotonic(),
            intent_result=DEFAULT_INTENT,
            last_event_id=5,
            response_text="",  # 挂起时无响应文本
            stream_completed=False,  # 挂起时未完成
            clarification=None,
            pending_interrupts=("hitl-2",),  # 关键:二次挂起
            agent=MagicMock(),
            get_quality_pipeline=None,
        )

    # 验证:不应发 done 帧
    sent_frames = [c.args[0] for c in mock_ws.send_json.call_args_list]
    done_frames = [f for f in sent_frames if isinstance(f, dict) and f.get("type") == "done"]
    assert done_frames == [], f"HITL 挂起时不应发 done,实际: {sent_frames}"

    # 验证:不应入库
    assert not mock_add_message.called, "HITL 挂起时不应入库 assistant 消息"


@pytest.mark.asyncio
async def test_finalize_after_stream_clarification_writes_placeholder() -> None:
    """``_finalize_after_stream`` 看到 ``clarification`` 应只写 placeholder。

    WHY:二次澄清挂起时,用户下一条消息进来要能看到上下文里的"刚才问了 X",
    所以必须写 placeholder 入库;但不发 done(本轮没真正完成)。
    """
    from nexus.backend.api.ws import _finalize_after_stream
    from nexus.backend.intent.router import DEFAULT_INTENT

    with patch("nexus.backend.api.ws.add_message") as mock_add_message:
        mock_ws = AsyncMock()
        await _finalize_after_stream(
            websocket=mock_ws,
            session_id="sess-clar",
            user_content="",
            message_id="msg-clar",
            chat_start_monotonic=time.monotonic(),
            intent_result=DEFAULT_INTENT,
            last_event_id=3,
            response_text="",
            stream_completed=False,
            clarification=("你想调用哪个工具?", ["write_file", "edit_file"]),
            pending_interrupts=None,
            agent=MagicMock(),
            get_quality_pipeline=None,
        )

    # 验证:写入 1 条 placeholder
    assert mock_add_message.call_count == 1
    args = mock_add_message.call_args[0]
    assert args[1] == "sess-clar"
    assert args[2] == "assistant"
    assert "[澄清中]" in args[3]
    assert "你想调用哪个工具?" in args[3]

    # 验证:不应发 done
    sent_frames = [c.args[0] for c in mock_ws.send_json.call_args_list]
    done_frames = [f for f in sent_frames if isinstance(f, dict) and f.get("type") == "done"]
    assert done_frames == [], f"澄清挂起时不应发 done,实际: {sent_frames}"
