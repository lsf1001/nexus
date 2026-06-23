"""Channel 核心接口定义。

提供所有 Channel 的抽象基类和统一消息格式。
"""

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .gateway import Gateway

logger = logging.getLogger(__name__)


class MessageType(StrEnum):
    """消息类型枚举"""

    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    VIDEO = "video"
    FILE = "file"
    EVENT = "event"


class ChannelType(StrEnum):
    """通道类型枚举 (前端 WebSocket 由 FastAPI /api/ws 直管,不走 Channel ABC)"""

    WECHAT = "wechat"
    FEISHU = "feishu"


class ChannelStatus(StrEnum):
    """通道状态枚举"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    STOPPING = "stopping"


class ChannelConfig(BaseModel):
    """通道配置"""

    channel_id: str = Field(..., description="通道唯一标识")
    channel_type: ChannelType = Field(..., description="通道类型")
    enabled: bool = Field(default=True, description="是否启用")
    name: str = Field(..., description="通道显示名称")
    auth_token: str | None = Field(default=None, description="Token 认证")
    allowed_users: list[str] = Field(default_factory=list, description="白名单用户")
    settings: dict[str, Any] = Field(default_factory=dict, description="通道特定配置")


class ChannelState(BaseModel):
    """通道运行时状态"""

    channel_id: str
    status: ChannelStatus = ChannelStatus.STOPPED
    last_error: str | None = None
    started_at: datetime | None = None
    message_count: int = 0
    error_count: int = 0


class ChannelMessage(BaseModel):
    """统一消息格式 - 所有 Channel 输出的标准消息格式"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="消息唯一ID")
    channel_id: str = Field(..., description="来源通道ID")
    channel_type: ChannelType = Field(..., description="来源通道类型")
    session_id: str = Field(..., description="会话ID")
    user_id: str = Field(..., description="用户ID（平台特定）")
    content: str = Field(..., description="消息内容")
    message_type: MessageType = Field(default=MessageType.TEXT, description="消息类型")
    raw_data: dict[str, Any] = Field(default_factory=dict, description="原始平台数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    reply_to: str | None = Field(default=None, description="回复目标消息ID")


class Channel(ABC):
    """Channel 抽象基类 - 所有通道必须实现此接口"""

    def __init__(self, config: ChannelConfig):
        self.config = config
        self.state = ChannelState(channel_id=config.channel_id)
        self._gateway: Gateway | None = None
        self._lock = asyncio.Lock()

    @abstractmethod
    async def start(self) -> None:
        """启动通道，开始接收消息"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止通道"""
        pass

    @abstractmethod
    async def send_message(self, message: ChannelMessage) -> None:
        """发送消息到通道（由 Gateway 调用）"""
        pass

    def get_channel_id(self) -> str:
        """获取通道ID"""
        return self.config.channel_id

    def get_channel_type(self) -> ChannelType:
        """获取通道类型"""
        return self.config.channel_type

    def get_status(self) -> ChannelStatus:
        """获取通道状态"""
        return self.state.status

    def bind_gateway(self, gateway: "Gateway") -> None:
        """绑定 Gateway 实例（用于通道向 Gateway 发送消息）"""
        self._gateway = gateway

    def _update_state(self, **kwargs) -> None:
        """更新通道状态"""
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)

    def _increment_message_count(self) -> None:
        """增加消息计数"""
        self.state.message_count += 1

    def _increment_error_count(self) -> None:
        """增加错误计数"""
        self.state.error_count += 1

    async def _safe_handle_message(self, message: ChannelMessage) -> None:
        """安全的消息处理包装"""
        try:
            if self._gateway:
                await self._gateway.route_message(message)
                self._increment_message_count()
            else:
                logger.warning(f"Channel {self.config.channel_id} not bound to gateway")
        except Exception as e:
            logger.error(f"Error handling message in {self.config.channel_id}: {e}")
            self._increment_error_count()
            self._update_state(status=ChannelStatus.ERROR, last_error=str(e))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.config.channel_id} status={self.state.status}>"
