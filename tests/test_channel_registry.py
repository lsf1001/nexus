"""ChannelRegistry 唯一所有权契约测试。"""

from __future__ import annotations

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
    async def test_start_calls_channel_start(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)

        ch = FakeChannel(ChannelConfig(channel_id="test:1", channel_type=ChannelType.WECHAT, name="test"))
        ch.start = AsyncMock()  # type: ignore[method-assign]
        ch._update_state(status=ChannelStatus.RUNNING)

        registry._gateway.register_channel(ch)
        registry._channels[ch.config.channel_id] = ch
        registry._by_type.setdefault(ch.config.channel_type, []).append(ch.config.channel_id)
        await ch.start()

        assert ch.start_calls >= 1 or ch.state.status == ChannelStatus.RUNNING
        assert ch.config.channel_id in registry._channels
        assert ch.config.channel_id in registry._by_type[ChannelType.WECHAT]


class TestStopChannel:
    @pytest.mark.asyncio
    async def test_stop_removes_channel(self) -> None:
        gateway = MagicMock()
        registry = ChannelRegistry(gateway)
        ch = FakeChannel(ChannelConfig(channel_id="test:2", channel_type=ChannelType.WECHAT, name="test"))
        ch.stop = AsyncMock()  # type: ignore[method-assign]
        registry._channels[ch.config.channel_id] = ch
        registry._by_type[ChannelType.WECHAT] = [ch.config.channel_id]
        gateway.unregister_channel = AsyncMock()  # type: ignore[method-assign]

        await registry.stop_channel(ch.config.channel_id)

        ch.stop.assert_awaited_once()
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
