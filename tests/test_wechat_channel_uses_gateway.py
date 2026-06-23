"""WeChatChannel 必须走 _safe_handle_message → Gateway,不走 on_message callback。

旧实现 wechat_channel.py:307-313 有 on_message callback 旁路,
重构后必须确认 _handle_incoming_message 走 Channel 基类的 _safe_handle_message 入口。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    ChannelMessage,
    ChannelType,
)
from nexus.backend.channels.wechat_channel import WeChatChannel


@pytest.mark.asyncio
async def test_incoming_message_calls_safe_handle_message() -> None:
    """WeChatChannel._handle_incoming_message 必须调 self._safe_handle_message。"""
    ch = WeChatChannel.__new__(WeChatChannel)  # 绕开 __init__ 不联网
    ch.config = MagicMock()
    ch.config.channel_id = "w:test"
    ch._account = MagicMock()
    ch._account.account_id = "acc_test"
    ch._update_state = MagicMock()  # type: ignore[method-assign]
    ch._safe_handle_message = AsyncMock()  # type: ignore[method-assign]

    raw_msg = {
        "from_user_id": "user1",
        "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
    }

    await ch._handle_incoming_message(raw_msg)

    ch._safe_handle_message.assert_awaited_once()
    called_msg = ch._safe_handle_message.await_args.args[0]
    assert isinstance(called_msg, ChannelMessage)
    assert called_msg.user_id == "user1"
    assert called_msg.content == "hello"
    assert called_msg.channel_type == ChannelType.WECHAT


@pytest.mark.asyncio
async def test_on_message_attribute_removed() -> None:
    """重构后 on_message 方法应不存在(旁路已删)。"""
    assert not hasattr(WeChatChannel, "on_message"), (
        "on_message callback 应在重构后删除,所有消息走 _safe_handle_message → Gateway"
    )
