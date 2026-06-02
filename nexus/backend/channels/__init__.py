"""Nexus Channel 架构 - 多通道支持模块

提供统一的消息通道抽象和 Gateway 路由。
"""

from .base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelState,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from .gateway import Gateway
from .registry import ChannelRegistry, create_channel_from_config

__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelMessage",
    "ChannelState",
    "ChannelStatus",
    "ChannelType",
    "MessageType",
    "Gateway",
    "ChannelRegistry",
    "create_channel_from_config",
]
