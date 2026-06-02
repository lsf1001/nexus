"""Gateway - 消息网关，Channel 消息的中转站。

负责：
- 消息路由（Channel → Agent Core）
- 响应分发（Agent Core → Channel）
- 会话绑定（session_id ↔ channel_id）
- 鉴权（token 验证）
"""

import asyncio
import logging
from typing import Any

from .base import Channel, ChannelMessage

logger = logging.getLogger(__name__)


class Gateway:
    """消息网关 - 所有 Channel 消息的中转站"""

    def __init__(
        self,
        agent: Any,
        db_session_manager: Any,
        db_messages: Any,
    ):
        """初始化 Gateway

        Args:
            agent: DeepAgents agent 实例
            db_session_manager: 会话管理模块（来自 db.py）
            db_messages: 消息管理模块（来自 db.py）
        """
        self.agent = agent
        self.db_session = db_session_manager
        self.db_messages = db_messages
        self._channels: dict[str, Channel] = {}
        self._session_to_channel: dict[str, str] = {}  # session_id -> channel_id
        self._user_to_session: dict[str, str] = {}  # user_id -> session_id
        self._lock = asyncio.Lock()

    def register_channel(self, channel: Channel) -> None:
        """注册通道

        Args:
            channel: Channel 实例
        """
        self._channels[channel.get_channel_id()] = channel
        channel.bind_gateway(self)
        logger.info(f"Channel registered: {channel}")

    async def unregister_channel(self, channel_id: str) -> None:
        """注销通道

        Args:
            channel_id: 通道ID
        """
        async with self._lock:
            if channel_id in self._channels:
                channel = self._channels.pop(channel_id)
                await channel.stop()
                logger.info(f"Channel unregistered: {channel_id}")

                # 清理会话映射
                sessions_to_remove = [sid for sid, cid in self._session_to_channel.items() if cid == channel_id]
                for sid in sessions_to_remove:
                    self._session_to_channel.pop(sid, None)

    async def route_message(self, message: ChannelMessage) -> None:
        """路由消息到 Agent Core

        Args:
            message: ChannelMessage 实例
        """
        try:
            # 1. 验证消息
            if not message.content:
                logger.warning(f"Empty message content from {message.channel_id}")
                return

            # 2. 获取或创建会话
            session_id = await self._get_or_create_session(message)

            # 3. 保存用户消息到数据库
            await self._save_message(session_id, "user", message)

            # 4. 调用 Agent 处理
            response_content = await self._call_agent(session_id, message)

            # 5. 保存助手响应
            if response_content:
                await self._save_message(session_id, "assistant", message, response_content)

                # 6. 发送响应到通道
                await self._send_response(message, response_content)

        except Exception as e:
            logger.error(f"Error routing message: {e}", exc_info=True)
            await self._send_error(message, str(e))

    async def _get_or_create_session(self, message: ChannelMessage) -> str:
        """获取或创建会话

        Args:
            message: ChannelMessage 实例

        Returns:
            session_id
        """
        user_key = f"{message.channel_id}:{message.user_id}"

        # 查找已有会话
        if user_key in self._user_to_session:
            session_id = self._user_to_session[user_key]
            # 更新会话时间
            await self.db_session.update_session(session_id)
            return session_id

        # 尝试从数据库获取
        existing = await self._find_existing_session(message)
        if existing:
            session_id = existing
        else:
            # 创建新会话
            session_id = message.session_id if message.session_id else f"{message.channel_id}:{message.user_id}"
            await self.db_session.create_session(
                session_id, title=message.content[:50] if message.content else "新会话"
            )

        # 绑定映射
        async with self._lock:
            self._user_to_session[user_key] = session_id
            self._session_to_channel[session_id] = message.channel_id

        return session_id

    async def _find_existing_session(self, message: ChannelMessage) -> str | None:
        """从数据库查找已有会话

        Args:
            message: ChannelMessage 实例

        Returns:
            session_id 或 None
        """
        try:
            await self.db_session.list_sessions(limit=10)
        except Exception:
            pass
        return None

    async def _call_agent(self, session_id: str, message: ChannelMessage) -> str:
        """调用 Agent 处理消息

        Args:
            session_id: 会话ID
            message: ChannelMessage 实例

        Returns:
            Agent 响应内容
        """
        try:
            # 获取对话历史
            history = await self.db_messages.get_conversation_history(session_id)

            # 构建消息列表
            messages = [{"role": "user", "content": message.content}]

            # 如果有历史，追加
            if history:
                messages = history + messages

            # 调用 Agent
            full_response = ""
            async for chunk in self.agent.astream({"messages": messages}, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue
                if "model" in chunk:
                    model_data = chunk.get("model", {})
                    if model_data and isinstance(model_data, dict):
                        msgs = model_data.get("messages", [])
                        for msg in msgs:
                            content = getattr(msg, "content", "") or ""
                            if content:
                                full_response += content

            return full_response

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            return f"抱歉，处理消息时出错: {str(e)}"

    async def _save_message(
        self,
        session_id: str,
        role: str,
        original_message: ChannelMessage,
        content: str | None = None,
    ) -> None:
        """保存消息到数据库

        Args:
            session_id: 会话ID
            role: 角色（user/assistant）
            original_message: 原始 ChannelMessage
            content: 实际保存的内容（用于 assistant）
        """
        try:
            import uuid

            msg_id = str(uuid.uuid4())
            msg_content = content or original_message.content

            await self.db_messages.add_message(
                msg_id=msg_id,
                session_id=session_id,
                role=role,
                content=msg_content,
                thinking_content=original_message.metadata.get("thinking"),
            )
        except Exception as e:
            logger.error(f"Error saving message: {e}")

    async def _send_response(self, message: ChannelMessage, content: str) -> None:
        """发送响应到正确的通道

        Args:
            message: 原始消息
            content: 响应内容
        """
        try:
            # 构建响应消息
            response = ChannelMessage(
                channel_id=message.channel_id,
                channel_type=message.channel_type,
                session_id=message.session_id,
                user_id=message.user_id,
                content=content,
                reply_to=message.id,
                metadata=message.metadata,
            )

            # 发送到对应通道
            channel = self._channels.get(message.channel_id)
            if channel:
                await channel.send_message(response)
            else:
                logger.warning(f"Channel {message.channel_id} not found for response")

        except Exception as e:
            logger.error(f"Error sending response: {e}")

    async def _send_error(self, message: ChannelMessage, error: str) -> None:
        """发送错误消息

        Args:
            message: 原始消息
            error: 错误信息
        """
        try:
            response = ChannelMessage(
                channel_id=message.channel_id,
                channel_type=message.channel_type,
                session_id=message.session_id,
                user_id=message.user_id,
                content=f"错误: {error}",
            )

            channel = self._channels.get(message.channel_id)
            if channel:
                await channel.send_message(response)

        except Exception as e:
            logger.error(f"Error sending error message: {e}")

    async def get_channel_status(self, channel_id: str) -> dict | None:
        """获取通道状态

        Args:
            channel_id: 通道ID

        Returns:
            通道状态字典
        """
        channel = self._channels.get(channel_id)
        if channel:
            return {
                "channel_id": channel.get_channel_id(),
                "type": channel.get_channel_type().value,
                "status": channel.get_status().value,
            }
        return None

    def get_all_channels(self) -> list[dict]:
        """获取所有通道状态

        Returns:
            通道状态列表
        """
        return [
            {
                "channel_id": ch.get_channel_id(),
                "type": ch.get_channel_type().value,
                "status": ch.get_status().value,
            }
            for ch in self._channels.values()
        ]
