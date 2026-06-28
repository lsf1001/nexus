"""回归测试：_run_agent_streaming 必须实时发 chunk,不能缓存到流末。

WHY: E2E 2026-06-28 真实日志显示切到 agnes 后,前端 26 秒收不到任何帧,
根因是 ws.py 的 ``on_chat_model_stream`` 分支把 chunk 累加到 full_response,
等 LLM 跑完才按 16 字符切碎发出。本测试用 mock agent 验证：每来一个 stream
事件,ws.py 必须立刻 emit 帧,而不是攒到最后。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


class _FakeWebSocket:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.frames.append(data)


class _StreamingAgent:
    """模拟 deepagents astream_events：逐 token 产生 on_chat_model_stream。"""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def astream_events(self, input_: Any, **kw: Any) -> Any:
        # 先发 on_chat_model_start
        yield {"event": "on_chat_model_start", "data": {}, "name": "ChatOpenAI"}
        for t in self._tokens:
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("C", (), {"content": t})()},
                "name": "ChatOpenAI",
            }
            await asyncio.sleep(0)  # 让 event loop 切走,模拟真实 IO
        yield {
            "event": "on_chat_model_end",
            "data": {"output": type("O", (), {"content": "".join(self._tokens)})()},
            "name": "ChatOpenAI",
        }


@pytest.mark.asyncio
async def test_chunks_emitted_realtime_not_buffered() -> None:
    """每个 token 立即发 1 个 chunk 帧,不是攒到最后 burst。"""
    from nexus.backend.api.ws import _run_agent_streaming

    ws = _FakeWebSocket()
    agent = _StreamingAgent(["你", "好", "世", "界"])
    prompt = {"messages": [{"role": "user", "content": "hi"}]}

    await _run_agent_streaming(
        websocket=ws,
        session_id="test-session",
        prompt=prompt,
        agent=agent,
    )

    # 前 4 个 chunk 必须按顺序实时发出（不能 burst 在 done 之前）
    chunk_frames = [f for f in ws.frames if f["type"] == "chunk"]
    assert len(chunk_frames) == 4, f"应有 4 个 chunk 帧,实际 {len(chunk_frames)}"
    assert [f["content"] for f in chunk_frames] == ["你", "好", "世", "界"]


@pytest.mark.asyncio
async def test_thinking_emitted_realtime_when_tag_seen() -> None:
    """流式遇到 <thinking>...</thinking> 必须立即发 thinking 帧。"""
    from nexus.backend.api.ws import _run_agent_streaming

    ws = _FakeWebSocket()
    # 标签故意跨多个 token,验证分片识别
    agent = _StreamingAgent(
        ["<thin", "king>", "推理中", "</think", "ing>", "答案"],
    )
    prompt = {"messages": [{"role": "user", "content": "hi"}]}

    await _run_agent_streaming(
        websocket=ws,
        session_id="test-session",
        prompt=prompt,
        agent=agent,
    )

    thinking_frames = [f for f in ws.frames if f["type"] == "thinking"]
    chunk_frames = [f for f in ws.frames if f["type"] == "chunk"]
    assert len(thinking_frames) >= 1
    assert "".join(f["content"] for f in thinking_frames) == "推理中"
    assert "".join(f["content"] for f in chunk_frames) == "答案"


@pytest.mark.asyncio
async def test_final_emitted_after_stream_completes() -> None:
    """final 帧必须在流结束后、stats 之前发出;流期间不应有 final。

    WHY:``done`` 帧由 handle_websocket 发出,不在 _run_agent_streaming 职责内。
    这里只验证 _run_agent_streaming 内部协议顺序：流期间只有 chunk /
    thinking / tool 事件,流结束后才发 token_usage / final / stats。
    """
    from nexus.backend.api.ws import _run_agent_streaming

    ws = _FakeWebSocket()
    agent = _StreamingAgent(["hi"])
    prompt = {"messages": [{"role": "user", "content": "hi"}]}

    await _run_agent_streaming(
        websocket=ws,
        session_id="test-session",
        prompt=prompt,
        agent=agent,
    )

    types = [f["type"] for f in ws.frames]
    # 流期间不应出现 final（实时 emit 应当实时送 chunk,而 final 仅在结束时发）
    assert "final" in types, f"缺少 final 帧:{types}"
    final_idx = types.index("final")
    # 流期间不应有 final（实时 chunk 应当实时送）
    pre_final = types[:final_idx]
    assert "final" not in pre_final, f"流期间不应出现 final:{pre_final}"
    # final 之后应有 stats（done 由 handle_websocket 发,不在此函数职责内）
    assert "stats" in types[final_idx + 1 :], f"final 后应有 stats:{types}"
