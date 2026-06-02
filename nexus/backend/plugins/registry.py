"""Plugin Registry - 插件注册表

参考 OpenClaw: openclaw/plugin-sdk
https://github.com/openclaw/openclaw/blob/main/docs/plugins/sdk-overview.md
"""

import logging
import threading
from collections.abc import Callable

from .channel import BaseChannel, ChannelConfig, ChannelStatus
from .manifest import ChannelManifest, PluginManifest

logger = logging.getLogger(__name__)


class PluginRegistry:
    """插件注册表

    统一的插件注册和发现机制
    """

    _channels: dict[str, BaseChannel] = {}
    _manifests: dict[str, PluginManifest] = {}
    _factories: dict[str, Callable] = {}
    _lock = threading.RLock()  # 并发保护

    # ========== 通道注册 ==========

    @classmethod
    def register_channel(
        cls,
        channel: BaseChannel,
        manifest: ChannelManifest | None = None,
    ) -> None:
        """注册通道插件

        参考 OpenClaw: plugin registration
        """
        with cls._lock:
            channel_id = channel.channel_id
            cls._channels[channel_id] = channel

            if manifest:
                cls._manifests[channel_id] = manifest

        logger.info(f"Registered channel plugin: {channel_id}")

    @classmethod
    def register_factory(cls, channel_type: str, factory: Callable) -> None:
        """注册通道工厂函数

        用于按需创建通道实例
        """
        with cls._lock:
            cls._factories[channel_type] = factory
        logger.info(f"Registered channel factory: {channel_type}")

    @classmethod
    def unregister_channel(cls, channel_id: str) -> None:
        """注销通道插件"""
        with cls._lock:
            if channel_id in cls._channels:
                cls._channels.pop(channel_id, None)
                cls._manifests.pop(channel_id, None)
                logger.info(f"Unregistered channel plugin: {channel_id}")

    # ========== 获取 ==========

    @classmethod
    def get_channel(cls, channel_id: str) -> BaseChannel | None:
        """获取通道插件"""
        with cls._lock:
            return cls._channels.get(channel_id)

    @classmethod
    def get_manifest(cls, channel_id: str) -> PluginManifest | None:
        """获取插件清单"""
        with cls._lock:
            return cls._manifests.get(channel_id)

    @classmethod
    def list_channels(cls) -> list[BaseChannel]:
        """列出所有通道"""
        with cls._lock:
            return list(cls._channels.values())

    @classmethod
    def list_channel_ids(cls) -> list[str]:
        """列出所有通道 ID"""
        with cls._lock:
            return list(cls._channels.keys())

    @classmethod
    def get_by_type(cls, channel_type: str) -> BaseChannel | None:
        """按类型获取通道"""
        with cls._lock:
            return cls._channels.get(channel_type)

    # ========== 状态 ==========

    @classmethod
    def get_connected_channels(cls) -> list[BaseChannel]:
        """获取已连接的通道"""
        with cls._lock:
            return [ch for ch in cls._channels.values() if ch.status == ChannelStatus.CONNECTED]

    @classmethod
    def get_channel_status(cls, channel_id: str) -> ChannelStatus | None:
        """获取通道状态"""
        with cls._lock:
            channel = cls._channels.get(channel_id)
            return channel.status if channel else None

    # ========== 生命周期 ==========

    @classmethod
    async def start_all(cls) -> None:
        """启动所有通道"""
        with cls._lock:
            channels = list(cls._channels.values())

        for channel in channels:
            if channel.status == ChannelStatus.DISCONNECTED:
                try:
                    await channel.start()
                except Exception as e:
                    logger.error(f"Failed to start channel {channel.channel_id}: {e}")

    @classmethod
    async def stop_all(cls) -> None:
        """停止所有通道"""
        with cls._lock:
            channels = list(cls._channels.values())

        for channel in channels:
            try:
                await channel.stop()
            except Exception as e:
                logger.error(f"Failed to stop channel {channel.channel_id}: {e}")

    @classmethod
    async def connect_all(cls) -> None:
        """连接所有通道"""
        with cls._lock:
            channels = list(cls._channels.values())

        for channel in channels:
            if channel.status == ChannelStatus.DISCONNECTED:
                try:
                    await channel.connect()
                except Exception as e:
                    logger.error(f"Failed to connect channel {channel.channel_id}: {e}")

    @classmethod
    async def disconnect_all(cls) -> None:
        """断开所有通道"""
        with cls._lock:
            channels = list(cls._channels.values())

        for channel in channels:
            if channel.status == ChannelStatus.CONNECTED:
                try:
                    await channel.disconnect()
                except Exception as e:
                    logger.error(f"Failed to disconnect channel {channel.channel_id}: {e}")

    # ========== 工厂方法 ==========

    @classmethod
    def create_channel(
        cls,
        channel_type: str,
        config: ChannelConfig,
    ) -> BaseChannel | None:
        """创建通道实例"""
        with cls._lock:
            factory = cls._factories.get(channel_type)

        if factory:
            channel = factory()
            return channel
        return None


def define_plugin_entry(
    manifest: PluginManifest,
    factory: Callable,
) -> Callable:
    """插件入口点装饰器

    参考 OpenClaw: definePluginEntry

    用法:
        @define_plugin_entry(ChannelManifest(...))
        def create_wechat_channel():
            return WechatChannel()
    """

    def decorator(func: Callable) -> Callable:
        PluginRegistry.register_factory(manifest.id, factory)
        PluginRegistry._manifests[manifest.id] = manifest
        return func

    if isinstance(manifest, ChannelManifest):
        return decorator

    return decorator


def define_channel_plugin_entry(
    manifest: ChannelManifest,
) -> Callable:
    """通道插件入口点装饰器

    参考 OpenClaw: defineChannelPluginEntry

    用法:
        @define_channel_plugin_entry(ChannelManifest(
            id="wechat",
            name="WeChat",
            ...
        ))
        def create_wechat_channel():
            return WechatChannel()
    """

    def decorator(func: Callable) -> Callable:
        PluginRegistry.register_factory(manifest.id, func)
        with PluginRegistry._lock:
            PluginRegistry._manifests[manifest.id] = manifest
        logger.info(f"Registered channel plugin entry: {manifest.id}")
        return func

    return decorator
