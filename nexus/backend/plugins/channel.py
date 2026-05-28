"""Channel Core - 通道核心基类

参考 OpenClaw: openclaw/plugin-sdk/channel-core
https://github.com/openclaw/openclaw/blob/main/docs/plugins/sdk-channel-plugins.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from .manifest import ChannelManifest
from .message import (
    AckPolicy,
    ChannelMessageAdapter,
    InboundMessage,
    OutboundMessage,
    TypingIndicator,
)
from .security import ChannelSecurity, SecurityResult, Sender
from .session import Session, SessionGrammar, SessionManager


class ChannelStatus(Enum):
    """通道状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class ChannelConfig:
    """通道配置"""
    channel_id: str
    enabled: bool = True
    settings: dict[str, Any] = field(default_factory=dict)
    credentials: Optional[dict[str, Any]] = None  # 敏感凭据


class BaseChannel(ABC):
    """通道基类

    所有通道插件的基类，参考 OpenClaw defineChannelPluginEntry
    """

    def __init__(self):
        self._manifest: Optional[ChannelManifest] = None
        self._config: Optional[ChannelConfig] = None
        self._status = ChannelStatus.DISCONNECTED
        self._security: Optional[ChannelSecurity] = None
        self._session_manager: Optional[SessionManager] = None
        self._message_adapter: Optional[ChannelMessageAdapter] = None
        self._session_grammar: Optional[SessionGrammar] = None

        # 回调
        self._on_message_callback: Optional[Callable] = None
        self._on_status_change_callback: Optional[Callable] = None
        self._on_error_callback: Optional[Callable] = None

    # ========== 属性 ==========

    @property
    def channel_id(self) -> str:
        """通道唯一标识"""
        return self._manifest.id if self._manifest else self.__class__.__name__

    @property
    def channel_name(self) -> str:
        """通道显示名称"""
        return self._manifest.name if self._manifest else self.__class__.__name__

    @property
    def manifest(self) -> ChannelManifest:
        """插件清单"""
        return self._manifest

    @property
    def status(self) -> ChannelStatus:
        """当前状态"""
        return self._status

    @property
    def session_manager(self) -> SessionManager:
        """会话管理器"""
        return self._session_manager

    # ========== 生命周期 ==========

    @abstractmethod
    async def initialize(self, config: ChannelConfig) -> None:
        """初始化通道

        参考 OpenClaw: plugin.initialize()
        """
        self._config = config

    @abstractmethod
    async def start(self) -> None:
        """启动通道

        参考 OpenClaw: 通道启动
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止通道

        参考 OpenClaw: 通道停止
        """
        pass

    # ========== 连接管理 ==========

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def reconnect(self) -> None:
        """重新连接"""
        pass

    # ========== 消息 ==========

    @abstractmethod
    async def send(self, message: OutboundMessage) -> Any:
        """发送消息

        参考 OpenClaw: outbound adapter.send()
        """
        pass

    async def send_typing(self, indicator: TypingIndicator) -> None:
        """发送打字状态（可选）"""
        pass

    async def ack_message(self, message: InboundMessage, policy: AckPolicy) -> None:
        """确认消息"""
        pass

    # ========== 回调注册 ==========

    def on_message(self, callback: Callable[[InboundMessage], None]) -> None:
        """注册消息回调

        参考 OpenClaw: core owns the message tool
        """
        self._on_message_callback = callback

    def on_status_change(self, callback: Callable[[ChannelStatus], None]) -> None:
        """注册状态变更回调"""
        self._on_status_change_callback = callback

    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """注册错误回调"""
        self._on_error_callback = callback

    # ========== 内部方法 ==========

    def _set_status(self, status: ChannelStatus) -> None:
        """设置状态并触发回调"""
        if self._status != status:
            self._status = status
            if self._on_status_change_callback:
                self._on_status_change_callback(status)

    def _dispatch_message(self, message: InboundMessage) -> None:
        """分发消息到回调"""
        if self._on_message_callback:
            self._on_message_callback(message)

    def _handle_error(self, error: Exception) -> None:
        """处理错误"""
        if self._on_error_callback:
            self._on_error_callback(error)

    # ========== 安全 ==========

    async def check_security(self, sender: Sender, content: str) -> SecurityResult:
        """安全检查"""
        if self._security:
            return await self._security.check_sender(sender)
        return SecurityResult.allow()

    # ========== 配置验证 ==========

    def validate_config(self, config: ChannelConfig) -> tuple[bool, str]:
        """验证配置

        返回 (是否有效, 错误信息)
        """
        if not config.channel_id:
            return False, "channel_id is required"
        return True, ""


class ChannelPlugin(BaseChannel):
    """通道插件

    完整的通道插件实现，包含所有接口
    """

    async def initialize(self, config: ChannelConfig) -> None:
        await super().initialize(config)

    async def start(self) -> None:
        self._set_status(ChannelStatus.CONNECTING)

    async def stop(self) -> None:
        self._set_status(ChannelStatus.STOPPED)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def reconnect(self) -> None:
        self._set_status(ChannelStatus.RECONNECTING)
        await self.disconnect()
        await self.connect()

    async def send(self, message: OutboundMessage) -> Any:
        if self._message_adapter:
            return await self._message_adapter.send(message)
        raise NotImplementedError("No message adapter configured")
