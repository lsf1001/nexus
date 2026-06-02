"""Channel Message Adapter - 通道消息适配器

参考 OpenClaw: openclaw/plugin-sdk/channel-outbound
https://github.com/openclaw/openclaw/blob/main/docs/plugins/sdk-channel-outbound.md
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageType(Enum):
    """消息类型"""

    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    VIDEO = "video"
    FILE = "file"
    EMOJI = "emoji"
    LOCATION = "location"
    CONTACT = "contact"


class MessageReceiptStatus(Enum):
    """消息回执状态"""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class AckPolicy(Enum):
    """消息确认策略"""

    NONE = "none"  # 无确认
    AUTO = "auto"  # 自动确认
    MANUAL = "manual"  # 手动确认


@dataclass
class MediaContent:
    """媒体内容"""

    url: str = ""
    mime_type: str = ""
    size: int = 0
    width: int | None = None
    height: int | None = None
    duration: float | None = None  # 音视频时长(秒)
    thumbnail: str | None = None  # 缩略图 URL


@dataclass
class MessageContent:
    """消息内容"""

    text: str = ""
    media: MediaContent | None = None

    # 扩展字段
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text_only(cls, text: str) -> "MessageContent":
        return cls(text=text)


@dataclass
class MessageReceipt:
    """消息回执"""

    message_id: str
    status: MessageReceiptStatus = MessageReceiptStatus.PENDING
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    error: str | None = None

    platform_id: str | None = None  # 平台返回的原始 ID


@dataclass
class InboundMessage:
    """收到的消息"""

    message_id: str
    channel_id: str

    # 发送者
    sender_id: str
    sender_name: str = ""
    sender_avatar: str = ""

    # 会话
    session_id: str
    conversation_type: str = "dm"  # dm, group

    # 内容
    content: MessageContent
    message_type: MessageType = MessageType.TEXT

    # 时间戳
    timestamp: int = 0

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    # 回执要求
    ack_policy: AckPolicy = AckPolicy.AUTO


@dataclass
class OutboundMessage:
    """发送的消息"""

    content: MessageContent
    to_user_id: str
    to_session_id: str | None = None

    # 消息类型
    message_type: MessageType = MessageType.TEXT

    # 回复
    reply_to_message_id: str | None = None

    # 选项
    options: dict[str, Any] = field(default_factory=dict)

    # 回执回调
    receipt_callback: Callable | None = None


@dataclass
class TypingIndicator:
    """打字状态"""

    session_id: str
    user_id: str
    is_typing: bool = True


# ========== Channel Message Adapter 接口 ==========


class ChannelMessageAdapter(ABC):
    """通道消息适配器接口

    参考 OpenClaw: defineChannelMessageAdapter
    """

    @abstractmethod
    async def send(self, message: OutboundMessage) -> MessageReceipt:
        """发送消息"""
        pass

    @abstractmethod
    def supports_capability(self, capability: str) -> bool:
        """检查是否支持某能力"""
        pass

    def capabilities(self) -> list[str]:
        """返回支持的能力列表"""
        return []


class TextOnlyAdapter(ChannelMessageAdapter):
    """仅文本适配器"""

    async def send(self, message: OutboundMessage) -> MessageReceipt:
        if message.content.media:
            raise NotImplementedError("This channel does not support media")
        return MessageReceipt(
            message_id=str(uuid.uuid4()),
            status=MessageReceiptStatus.SENT,
        )

    def supports_capability(self, capability: str) -> bool:
        return capability in ["text", "basic"]


class MediaAdapter(TextOnlyAdapter):
    """媒体支持适配器"""

    def __init__(self):
        super().__init__()
        self._caps = ["text", "media", "basic"]

    async def send(self, message: OutboundMessage) -> MessageReceipt:
        return await super().send(message)

    def supports_capability(self, capability: str) -> bool:
        return capability in self._caps


class TypingSupportAdapter(ChannelMessageAdapter):
    """支持打字状态的适配器"""

    @abstractmethod
    async def send_typing(self, indicator: TypingIndicator) -> None:
        """发送打字状态"""
        pass


def create_message_receipt(
    message_id: str,
    status: MessageReceiptStatus = MessageReceiptStatus.SENT,
    **kwargs,
) -> MessageReceipt:
    """创建消息回执的辅助函数"""
    return MessageReceipt(
        message_id=message_id,
        status=status,
        **kwargs,
    )
