"""Channel Session - 通道会话管理

参考 OpenClaw: openclaw/plugin-sdk/sdk-channel-turn
https://github.com/openclaw/openclaw/blob/main/docs/plugins/sdk-channel-turn.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ConversationType(Enum):
    """会话类型"""

    DM = "dm"  # 私信
    GROUP = "group"  # 群聊
    CHANNEL = "channel"  # 频道


@dataclass
class Session:
    """通道会话

    代表一个持续的对话会话
    """

    session_id: str  # 会话 ID（平台相关）
    channel_id: str  # 通道 ID
    conversation_type: ConversationType = ConversationType.DM

    # 参与者
    participants: list[str] = field(default_factory=list)  # 用户 ID 列表

    # 会话标识（用于路由）
    base_session_id: str | None = None  # 基础会话 ID
    thread_id: str | None = None  # 线程 ID
    parent_id: str | None = None  # 父消息 ID

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    # 状态
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now())
    updated_at: datetime = field(default_factory=lambda: datetime.now())

    def update(self) -> None:
        """更新会话时间"""
        self.updated_at = datetime.now()


@dataclass
class SessionGrammar:
    """会话语法

    定义如何将平台特定的会话 ID 映射到基础结构
    """

    # 格式模板
    session_id_template: str = "{channel}:{type}:{id}"
    thread_template: str | None = None
    parent_template: str | None = None

    # 正则解析
    session_id_pattern: str | None = None
    thread_pattern: str | None = None

    @abstractmethod
    def parse_session_id(self, raw_id: str) -> dict[str, Any]:
        """解析原始会话 ID"""
        pass

    @abstractmethod
    def format_session_id(
        self,
        channel: str,
        conv_type: ConversationType,
        platform_id: str,
    ) -> str:
        """格式化会话 ID"""
        pass


class DefaultSessionGrammar(SessionGrammar):
    """默认会话语法"""

    def parse_session_id(self, raw_id: str) -> dict[str, Any]:
        """解析: channel:type:platform_id"""
        parts = raw_id.split(":")
        if len(parts) >= 3:
            return {
                "channel": parts[0],
                "type": parts[1],
                "platform_id": ":".join(parts[2:]),
            }
        return {
            "channel": "unknown",
            "type": "dm",
            "platform_id": raw_id,
        }

    def format_session_id(
        self,
        channel: str,
        conv_type: ConversationType,
        platform_id: str,
    ) -> str:
        return f"{channel}:{conv_type.value}:{platform_id}"


class SessionManager(ABC):
    """会话管理器

    负责会话的创建、查找、路由
    """

    @abstractmethod
    async def get_or_create_session(
        self,
        channel_id: str,
        session_id: str,
        conversation_type: ConversationType = ConversationType.DM,
        participants: list[str] | None = None,
    ) -> Session:
        """获取或创建会话"""
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Session | None:
        """获取会话"""
        pass

    @abstractmethod
    async def update_session(self, session: Session) -> None:
        """更新会话"""
        pass

    @abstractmethod
    async def resolve_thread_parent(
        self,
        session_id: str,
        message_id: str,
    ) -> str | None:
        """解析线程父消息

        返回父消息所在的会话 ID
        """
        pass


class InMemorySessionManager(SessionManager):
    """内存会话管理器（默认实现）"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    async def get_or_create_session(
        self,
        channel_id: str,
        session_id: str,
        conversation_type: ConversationType = ConversationType.DM,
        participants: list[str] | None = None,
    ) -> Session:
        if session_id in self._sessions:
            return self._sessions[session_id]

        session = Session(
            session_id=session_id,
            channel_id=channel_id,
            conversation_type=conversation_type,
            participants=participants or [],
        )
        self._sessions[session_id] = session
        return session

    async def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def update_session(self, session: Session) -> None:
        session.update()
        self._sessions[session.session_id] = session

    async def resolve_thread_parent(
        self,
        session_id: str,
        message_id: str,
    ) -> str | None:
        return session_id  # 默认返回当前会话
