"""Gateway.route_message 契约测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from nexus.backend.channels.gateway import Gateway


class FakeChannel(Channel):
    """Gateway 测试用 channel,记录 send_message 调用。"""

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self.sent: list[ChannelMessage] = []
        self._update_state(status=ChannelStatus.RUNNING)

    async def start(self) -> None:
        self._update_state(status=ChannelStatus.RUNNING)

    async def stop(self) -> None:
        self._update_state(status=ChannelStatus.STOPPED)

    async def send_message(self, message: ChannelMessage) -> None:
        self.sent.append(message)


def _make_gateway(agent_text: str = "hello back") -> tuple[Gateway, FakeChannel, dict[str, Any]]:
    """构造 Gateway + FakeChannel + mock 依赖。"""
    ch = FakeChannel(
        ChannelConfig(
            channel_id="w:test_user",
            channel_type=ChannelType.WECHAT,
            name="test",
        )
    )

    sessions_module = MagicMock()
    sessions_module.find_latest_session_by_user.return_value = None  # 强制新建
    sessions_module.create_session = MagicMock()
    sessions_module.build_prompt.return_value = {"messages": [{"role": "user", "content": "hi"}]}

    messages_module = MagicMock()
    # db.add_message 是同步阻塞 IO,Gateway 内部用 asyncio.to_thread 切走。
    # 这里用 sync MagicMock 反映真实 db 接口,断言走 call_count。
    messages_module.add_message = MagicMock()

    # mock deepagents agent.astream
    agent = MagicMock()

    async def _astream(input_dict: dict[str, Any], stream_mode: str) -> Any:
        assert stream_mode == "updates"
        yield {"model": {"messages": [MagicMock(content=agent_text)]}}

    agent.astream = _astream

    gateway = Gateway(agent=agent, sessions_module=sessions_module, messages_module=messages_module)
    gateway.register_channel(ch)
    return gateway, ch, {"sessions": sessions_module, "messages": messages_module}


def _msg(content: str = "hi", user_id: str = "user1") -> ChannelMessage:
    return ChannelMessage(
        channel_id="w:test_user",
        channel_type=ChannelType.WECHAT,
        session_id="ignored",
        user_id=user_id,
        content=content,
        message_type=MessageType.TEXT,
    )


class TestRouteMessageHappyPath:
    @pytest.mark.asyncio
    async def test_user_and_assistant_messages_added(self) -> None:
        gateway, _ch, mocks = _make_gateway("the answer")
        await gateway.route_message(_msg())
        assert mocks["messages"].add_message.call_count == 2
        second_call = mocks["messages"].add_message.call_args_list[1]
        assert second_call.args[2] == "assistant"
        assert second_call.args[3] == "the answer"

    @pytest.mark.asyncio
    async def test_response_sent_to_channel(self) -> None:
        gateway, ch, _ = _make_gateway("the answer")
        await gateway.route_message(_msg())
        assert len(ch.sent) == 1
        assert ch.sent[0].content == "the answer"
        assert ch.sent[0].reply_to is not None

    @pytest.mark.asyncio
    async def test_session_created_on_first_message(self) -> None:
        gateway, _ch, mocks = _make_gateway()
        await gateway.route_message(_msg(user_id="u_new"))
        mocks["sessions"].create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_reused_when_resumed(self) -> None:
        gateway, _ch, mocks = _make_gateway()
        mocks["sessions"].find_latest_session_by_user.return_value = "existing_sid"
        await gateway.route_message(_msg(user_id="u_resume"))
        mocks["sessions"].create_session.assert_not_called()


class TestRouteMessageError:
    @pytest.mark.asyncio
    async def test_agent_raises_sends_error_to_channel(self) -> None:
        gateway, ch, _ = _make_gateway()

        async def _boom(input_dict: dict[str, Any], stream_mode: str) -> Any:
            raise RuntimeError("agent down")
            yield  # noqa: F841  # unreachable but required for async generator signature

        gateway._agent.astream = _boom  # type: ignore[assignment]

        await gateway.route_message(_msg())
        assert len(ch.sent) == 1
        assert "处理消息时出错" in ch.sent[0].content
        assert "agent down" in ch.sent[0].content


class TestCallAgentStripThinking:
    @pytest.mark.asyncio
    async def test_strips_think_tags(self) -> None:
        gateway, _ch, _ = _make_gateway(agent_text="x")

        async def _astream_with_think(input_dict: dict[str, Any], stream_mode: str) -> Any:
            yield {"model": {"messages": [MagicMock(content=" thought ")]}}
            yield {"model": {"messages": [MagicMock(content="real answer")]}}

        gateway._agent.astream = _astream_with_think  # type: ignore[assignment]

        text = await gateway._call_agent({"messages": []})
        assert "<think>" not in text
        assert "</think>" not in text
        assert "thought" not in text
        assert "real answer" in text


class TestRouteMessageEmptyContent:
    @pytest.mark.asyncio
    async def test_empty_content_returns_early(self) -> None:
        gateway, ch, mocks = _make_gateway()
        await gateway.route_message(_msg(content=""))
        mocks["messages"].add_message.assert_not_called()
        assert len(ch.sent) == 0


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_called_with_response(self) -> None:
        gateway, _ch, _ = _make_gateway("hello")
        broadcast_fn = AsyncMock()
        gateway.set_broadcast(ChannelType.WECHAT, broadcast_fn)
        await gateway.route_message(_msg())
        broadcast_fn.assert_awaited_once()
        bcast_msg = broadcast_fn.await_args.args[0]
        assert bcast_msg.content == "hello"

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_break_send(self) -> None:
        gateway, ch, _ = _make_gateway("hello")
        broadcast_fn = AsyncMock(side_effect=RuntimeError("ws down"))
        gateway.set_broadcast(ChannelType.WECHAT, broadcast_fn)
        await gateway.route_message(_msg())
        assert len(ch.sent) == 1
        assert ch.sent[0].content == "hello"
