"""WebSocket 通道 - 从 main.py 迁移。

保持向后兼容，现有 /api/ws 端点不变。
"""

import asyncio
import logging
import re
import uuid
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from .base import Channel, ChannelConfig, ChannelMessage, ChannelStatus, ChannelType, MessageType

logger = logging.getLogger(__name__)

# 从 main.py 迁移的配置
MAX_HISTORY_MESSAGES = 100


class WebSocketChannel(Channel):
    """WebSocket 通道 - 迁移自 main.py websocket_endpoint"""

    def __init__(self, config: ChannelConfig, token: str):
        """初始化 WebSocket 通道

        Args:
            config: ChannelConfig
            token: WebSocket 认证 token
        """
        super().__init__(config)
        self.token = token
        self._active_connections: dict[str, WebSocket] = {}
        self._histories: dict[str, list[dict]] = {}  # session_id -> conversation_history

    async def start(self) -> None:
        """启动通道 - WebSocket 通道无需启动，连接由 FastAPI 管理"""
        self._update_state(status=ChannelStatus.RUNNING, started_at=None)
        logger.info(f"WebSocket Channel {self.config.channel_id} initialized")

    async def stop(self) -> None:
        """停止通道"""
        self._update_state(status=ChannelStatus.STOPPING)
        # 关闭所有连接
        for ws in self._active_connections.values():
            try:
                await ws.close()
            except Exception:
                pass
        self._active_connections.clear()
        self._histories.clear()
        self._update_state(status=ChannelStatus.STOPPED)
        logger.info(f"WebSocket Channel {self.config.channel_id} stopped")

    async def send_message(self, message: ChannelMessage) -> None:
        """发送消息到 WebSocket 客户端

        Args:
            message: ChannelMessage
        """
        ws = self._active_connections.get(message.session_id)
        if not ws:
            logger.warning(f"No WebSocket connection for session {message.session_id}")
            return

        try:
            # 发送文本响应
            if message.content:
                # 分块发送：每帧约 16 字符，UI 打字效果更顺滑
                chunk_size = 16
                for i in range(0, len(message.content), chunk_size):
                    chunk = message.content[i:i + chunk_size]
                    await ws.send_json({
                        "type": "chunk",
                        "content": chunk,
                    })

                await ws.send_json({
                    "type": "final",
                    "content": message.content,
                })

            await ws.send_json({
                "type": "done",
                "content": "",
            })

        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")

    async def handle_connection(self, websocket: WebSocket, session_id: Optional[str] = None) -> None:
        """处理 WebSocket 连接

        Args:
            websocket: WebSocket 连接
            session_id: 可选的会话ID
        """
        # Token 验证
        token = websocket.query_params.get("token")
        if token != self.token:
            await websocket.close(code=4001)
            return

        await websocket.accept()
        conn_id = str(uuid.uuid4())
        self._active_connections[conn_id] = websocket

        # 获取或创建会话ID
        if not session_id:
            session_id = websocket.query_params.get("session_id")

        if session_id:
            # 从数据库加载历史
            if session_id not in self._histories:
                self._histories[session_id] = []
        else:
            session_id = conn_id
            self._histories[session_id] = []

        try:
            while True:
                data = await websocket.receive_json()
                user_content = data.get("content", "")
                msg_session_id = data.get("session_id") or session_id
                msg_title = data.get("title")

                if not user_content:
                    continue

                # 添加用户消息到历史
                history = self._histories.get(msg_session_id, [])
                history.append({"role": "user", "content": user_content})

                # 限制历史消息数量
                if len(history) > MAX_HISTORY_MESSAGES:
                    history = history[-MAX_HISTORY_MESSAGES:]
                self._histories[msg_session_id] = history

                # 构建 ChannelMessage
                channel_msg = ChannelMessage(
                    channel_id=self.config.channel_id,
                    channel_type=ChannelType.WEBSOCKET,
                    session_id=msg_session_id,
                    user_id=msg_session_id,  # WebSocket 用 session_id 作为 user_id
                    content=user_content,
                    metadata={"history": history},
                )

                # 发送到 Gateway
                await self._safe_handle_message(channel_msg)

        except WebSocketDisconnect:
            logger.info(f"WebSocket client disconnected: {conn_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self._active_connections.pop(conn_id, None)

    def _process_agent_response(self, response: str) -> tuple[str, str]:
        """处理 Agent 响应，提取思考和回复

        Args:
            response: Agent 原始响应

        Returns:
            (thinking_text, response_text)
        """
        normalized = response.replace('<think>', '<thinking>').replace('</think>', '</thinking>')

        thinking_parts = re.findall(r'<thinking>(.*?)</thinking>', normalized, flags=re.DOTALL)
        response_text = re.sub(r'<thinking>.*?</thinking>', '', normalized, flags=re.DOTALL).strip()
        thinking_text = '\n'.join(thinking_parts)

        return thinking_text, response_text