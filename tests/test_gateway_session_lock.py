"""Gateway._get_or_create_session 并发锁测试。

验证同 user_key 并发 N 个 route_message 只创建 1 个 session。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    ChannelConfig,
    ChannelMessage,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from nexus.backend.channels.gateway import Gateway


class StubChannel:
    def __init__(self) -> None:
        self.config = ChannelConfig(
            channel_id="w:lock_test",
            channel_type=ChannelType.WECHAT,
            name="lock_test",
        )
        self.state = MagicMock()
        self.state.status = ChannelStatus.RUNNING

    async def send_message(self, message: ChannelMessage) -> None:
        pass

    def bind_gateway(self, gateway) -> None:
        pass


@pytest.mark.asyncio
async def test_concurrent_same_user_creates_one_session() -> None:
    sessions_module = MagicMock()
    sessions_module.find_latest_session_by_user.return_value = None
    sessions_module.create_session = MagicMock()
    sessions_module.update_session = MagicMock()
    sessions_module.get_session.return_value = {"session_id": "x"}

    messages_module = MagicMock()
    messages_module.add_message = AsyncMock()

    agent = MagicMock()

    async def _astream(input_dict, stream_mode):
        yield {"model": {"messages": [MagicMock(content="hi")]}}

    agent.astream = _astream

    gateway = Gateway(
        agent=agent,
        sessions_module=sessions_module,
        messages_module=messages_module,
    )
    gateway.register_channel(StubChannel())  # type: ignore[arg-type]

    msg = ChannelMessage(
        channel_id="w:lock_test",
        channel_type=ChannelType.WECHAT,
        session_id="ignored",
        user_id="concurrent_user",
        content="hi",
        message_type=MessageType.TEXT,
    )

    import asyncio

    await asyncio.gather(*[gateway.route_message(msg) for _ in range(10)])

    assert sessions_module.create_session.call_count == 1
