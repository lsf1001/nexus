"""ChannelRegistry - Channel 实例的工厂和生命周期管理器"""

import logging
from typing import Any

from .base import Channel, ChannelConfig, ChannelType

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """Channel 注册表 - 管理所有 Channel 实例"""

    def __init__(self):
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        """注册 Channel 实例

        Args:
            channel: Channel 实例
        """
        channel_id = channel.get_channel_id()
        self._channels[channel_id] = channel
        logger.info(f"Channel registered: {channel_id}")

    def unregister(self, channel_id: str) -> None:
        """注销 Channel 实例

        Args:
            channel_id: 通道ID
        """
        if channel_id in self._channels:
            self._channels.pop(channel_id)
            logger.info(f"Channel unregistered: {channel_id}")

    def get(self, channel_id: str) -> Channel | None:
        """获取 Channel 实例

        Args:
            channel_id: 通道ID

        Returns:
            Channel 实例或 None
        """
        return self._channels.get(channel_id)

    def get_by_type(self, channel_type: ChannelType) -> list[Channel]:
        """获取指定类型的所有 Channel

        Args:
            channel_type: 通道类型

        Returns:
            Channel 列表
        """
        return [ch for ch in self._channels.values() if ch.get_channel_type() == channel_type]

    def list_all(self) -> list[Channel]:
        """列出所有 Channel

        Returns:
            所有 Channel 实例
        """
        return list(self._channels.values())

    async def start_all(self) -> None:
        """启动所有 Channel"""
        for channel in self._channels.values():
            try:
                await channel.start()
            except Exception as e:
                logger.error(f"Failed to start channel {channel.get_channel_id()}: {e}")

    async def stop_all(self) -> None:
        """停止所有 Channel"""
        for channel in self._channels.values():
            try:
                await channel.stop()
            except Exception as e:
                logger.error(f"Failed to stop channel {channel.get_channel_id()}: {e}")


def create_channel_from_config(
    config: ChannelConfig,
    **kwargs: Any,
) -> Channel:
    """根据配置创建 Channel 实例

    Args:
        config: ChannelConfig
        **kwargs: 传递给 Channel 构造函数的额外参数

    Returns:
        Channel 实例

    Raises:
        ValueError: 不支持的通道类型
    """
    channel_type = config.channel_type

    if channel_type == ChannelType.WEBSOCKET:
        from .websocket import WebSocketChannel

        token = kwargs.get("token", "")
        return WebSocketChannel(config=config, token=token)

    elif channel_type == ChannelType.WECHAT:
        from .wechat import WeChatChannel

        token = kwargs.get("token", "")
        return WeChatChannel(config=config, token=token)

    elif channel_type == ChannelType.FEISHU:
        raise NotImplementedError("Feishu channel not implemented yet")

    else:
        raise ValueError(f"Unsupported channel type: {channel_type}")
