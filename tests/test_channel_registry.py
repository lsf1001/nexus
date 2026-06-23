"""ChannelRegistry 唯一所有权契约测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.backend.channels.base import (
    Channel,
    ChannelConfig,
    ChannelStatus,
    ChannelType,
)
from nexus.backend.channels.registry import ChannelRegistry


class FakeChannel(Channel):
    """测试用 fake channel,记录 start/stop 调用次数。"""

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1
        self._update_state(status=ChannelStatus.RUNNING)

    async def stop(self) -> None:
        self.stop_calls += 1
        self._update_state(status=ChannelStatus.STOPPED)

    async def send_message(self, message) -> None:  # noqa: ARG002
        pass


class TestStartChannel:
    @pytest.mark.asyncio
    async def test_start_registers_and_starts_channel(self) -> None:
        """端到端验证 start_channel 真正把 channel 装进 Registry 并 start。"""
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)

        # 用 FakeChannel 替换工厂,避免触发真实 WeChatChannel 的网络连接
        from nexus.backend.channels import registry as reg_module

        real_factory = reg_module.create_channel_from_config

        def fake_factory(config: ChannelConfig, **kwargs: Any) -> Channel:
            return FakeChannel(config)

        reg_module.create_channel_from_config = fake_factory
        try:
            config = ChannelConfig(channel_id="test:1", channel_type=ChannelType.WECHAT, name="test")
            ch = await registry.start_channel(config)
        finally:
            reg_module.create_channel_from_config = real_factory

        assert ch.config.channel_id in registry._channels
        assert ch.config.channel_id in registry._by_type[ChannelType.WECHAT]
        assert ch.state.status == ChannelStatus.RUNNING
        assert ch.start_calls == 1


class TestStartChannelRollback:
    """start() 失败时必须回滚:从 _channels / _by_type / Gateway 注销。"""

    @pytest.mark.asyncio
    async def test_start_raises_rollback_removes_channel(self) -> None:
        gateway = MagicMock()
        gateway.unregister_channel = AsyncMock()  # type: ignore[method-assign]
        registry = ChannelRegistry(gateway)

        class BrokenChannel(Channel):
            async def start(self) -> None:
                raise RuntimeError("intentional failure for test")

            async def stop(self) -> None:
                pass

            async def send_message(self, message: Any) -> None:
                pass

        from nexus.backend.channels import registry as reg_module

        real_factory = reg_module.create_channel_from_config

        def broken_factory(config: ChannelConfig, **kwargs: Any) -> Channel:
            return BrokenChannel(config)

        reg_module.create_channel_from_config = broken_factory
        try:
            with pytest.raises(RuntimeError, match="intentional failure for test"):
                await registry.start_channel(
                    ChannelConfig(
                        channel_id="rb:1",
                        channel_type=ChannelType.WECHAT,
                        name="rb",
                    ),
                )
        finally:
            reg_module.create_channel_from_config = real_factory

        assert "rb:1" not in registry._channels
        assert "rb:1" not in registry._by_type.get(ChannelType.WECHAT, [])
        gateway.unregister_channel.assert_awaited_once_with("rb:1")


class TestStopChannel:
    @pytest.mark.asyncio
    async def test_stop_removes_channel(self) -> None:
        """stop_channel 委托 Gateway 真正调一次 stop(无双调用),并清空 Registry。"""
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(channel_id="test:2", channel_type=ChannelType.WECHAT, name="test"))
        registry._channels[ch.config.channel_id] = ch
        registry._by_type[ChannelType.WECHAT] = [ch.config.channel_id]

        # 模拟 Gateway.unregister_channel 内部行为:被调时 await channel.stop()
        async def fake_unregister(channel_id: str) -> None:
            await ch.stop()

        gateway.unregister_channel = AsyncMock(side_effect=fake_unregister)  # type: ignore[method-assign]

        await registry.stop_channel(ch.config.channel_id)

        # Gateway 接管 stop,无双调用
        gateway.unregister_channel.assert_awaited_once_with(ch.config.channel_id)
        assert ch.stop_calls == 1
        assert ch.config.channel_id not in registry._channels
        assert ch.config.channel_id not in registry._by_type[ChannelType.WECHAT]


class TestGetActiveByType:
    def test_returns_running_only(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)

        ch_stopped = FakeChannel(ChannelConfig(channel_id="s:1", channel_type=ChannelType.WECHAT, name="s"))
        ch_stopped._update_state(status=ChannelStatus.STOPPED)
        registry._channels["s:1"] = ch_stopped
        registry._by_type[ChannelType.WECHAT] = ["s:1"]

        ch_running = FakeChannel(ChannelConfig(channel_id="r:1", channel_type=ChannelType.WECHAT, name="r"))
        ch_running._update_state(status=ChannelStatus.RUNNING)
        registry._channels["r:1"] = ch_running
        registry._by_type[ChannelType.WECHAT].append("r:1")

        active = registry.get_active_by_type(ChannelType.WECHAT)
        assert active is not None
        assert active.config.channel_id == "r:1"

    def test_returns_none_when_no_running(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(channel_id="x:1", channel_type=ChannelType.WECHAT, name="x"))
        ch._update_state(status=ChannelStatus.STOPPED)
        registry._channels["x:1"] = ch
        registry._by_type[ChannelType.WECHAT] = ["x:1"]

        assert registry.get_active_by_type(ChannelType.WECHAT) is None


class TestDuplicateStart:
    """同 type 已 RUNNING 再 start 抛 ValueError。"""

    @pytest.mark.asyncio
    async def test_duplicate_running_raises(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(channel_id="dup:1", channel_type=ChannelType.WECHAT, name="dup"))
        ch._update_state(status=ChannelStatus.RUNNING)
        registry._channels["dup:1"] = ch
        registry._by_type[ChannelType.WECHAT] = ["dup:1"]

        with pytest.raises(ValueError, match="already running"):
            await registry.start_channel(
                ChannelConfig(channel_id="dup:2", channel_type=ChannelType.WECHAT, name="dup2"),
            )
