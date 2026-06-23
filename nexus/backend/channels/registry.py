"""ChannelRegistry - Channel 实例的唯一所有权管理器。

所有 Channel 创建 / 启动 / 停止 / 查询都走本类,不再有散落的全局状态。
取代旧的 _wechat_sessions / wechat_state._active_channel。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import Channel, ChannelConfig, ChannelStatus, ChannelType

if TYPE_CHECKING:
    from .gateway import Gateway

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """所有 Channel 实例的唯一 owner。

    职责:
      - start_channel: 工厂方法,创建 + register + start 一条龙
      - stop_channel: 停 + 注销
      - get_active_by_type: 取该类型 RUNNING 的 channel
      - list_all: 给 /api/channels 用
    """

    def __init__(self, gateway: Gateway) -> None:
        self._gateway = gateway
        self._channels: dict[str, Channel] = {}
        self._by_type: dict[ChannelType, list[str]] = {}

    async def start_channel(self, config: ChannelConfig, **kwargs: Any) -> Channel:
        """创建 + register + start; 同 type 已 RUNNING 抛 ValueError。

        若 ch.start() 失败,会回滚:从 _channels / _by_type / Gateway 注销。
        """
        existing = self.get_active_by_type(config.channel_type)
        if existing is not None:
            raise ValueError(f"{config.channel_type.value} channel already running: {existing.config.channel_id}")

        ch = create_channel_from_config(config, **kwargs)
        self._gateway.register_channel(ch)
        self._channels[ch.config.channel_id] = ch
        self._by_type.setdefault(config.channel_type, []).append(ch.config.channel_id)
        try:
            await ch.start()
        except Exception:
            # 回滚:从 registry + gateway 注销,避免半注册状态泄漏
            self._channels.pop(ch.config.channel_id, None)
            cid_list = self._by_type.get(ch.config.channel_type, [])
            if ch.config.channel_id in cid_list:
                cid_list.remove(ch.config.channel_id)
            try:
                await self._gateway.unregister_channel(ch.config.channel_id)
            except Exception:
                logger.warning("rollback: gateway.unregister_channel failed")
            raise
        logger.info(f"Channel started: {ch}")
        return ch

    async def stop_channel(self, channel_id: str) -> None:
        """从 Registry 注销并交由 Gateway 负责 stop + 清理会话映射。

        注意:channel.stop() 由 Gateway.unregister_channel 内部调用,
        本方法不再重复调用,避免双重 stop。
        """
        ch = self._channels.pop(channel_id, None)
        if ch is None:
            return
        cid_list = self._by_type.get(ch.config.channel_type, [])
        if channel_id in cid_list:
            cid_list.remove(channel_id)
        await self._gateway.unregister_channel(channel_id)
        logger.info(f"Channel stopped: {channel_id}")

    def get(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)

    def get_active_by_type(self, ch_type: ChannelType) -> Channel | None:
        """取该类型第一个 RUNNING 通道。"""
        for cid in self._by_type.get(ch_type, []):
            ch = self._channels.get(cid)
            if ch and ch.state.status == ChannelStatus.RUNNING:
                return ch
        return None

    def list_all(self) -> list[Channel]:
        return list(self._channels.values())

    async def stop_all(self) -> None:
        for cid in list(self._channels.keys()):
            await self.stop_channel(cid)


def create_channel_from_config(
    config: ChannelConfig,
    **kwargs: Any,
) -> Channel:
    """根据配置创建 Channel 实例(纯工厂,不 register 不 start)。

    Raises:
        NotImplementedError: FEISHU 未实现
        ValueError: 不支持的 channel_type
    """
    channel_type = config.channel_type

    if channel_type == ChannelType.WECHAT:
        from .wechat_channel import WeChatChannel

        token = kwargs.get("token", "")
        return WeChatChannel(config=config, token=token)

    if channel_type == ChannelType.FEISHU:
        raise NotImplementedError("Feishu channel not implemented yet")

    raise ValueError(f"Unsupported channel type: {channel_type}")
