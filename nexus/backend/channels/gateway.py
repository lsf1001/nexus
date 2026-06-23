"""Gateway - IM 消息中央路由。

取代原 main.py 中 _handle_wechat_message / _process_wechat_message 的业务逻辑。
所有 Channel 收到消息后必须构造 ChannelMessage 调 self._gateway.route_message()。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .base import Channel, ChannelMessage, ChannelType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class Gateway:
    """IM 消息的中央路由。

    流程: route_message(msg)
      1. _get_or_create_session(msg)       会话锁串行化
      2. db.add_message(user, msg)
      3. _call_agent(prompt)               抽出的共用 runner
      4. db.add_message(assistant, response)
      5. channel.send_message(response)    发回 IM
      6. broadcast(ch_type, response)      推给 WS 客户端
    """

    def __init__(
        self,
        *,
        agent: Any,
        sessions_module: Any,
        messages_module: Any,
    ) -> None:
        self._agent = agent
        self._sessions = sessions_module
        self._messages = messages_module
        self._channels: dict[str, Channel] = {}
        self._session_to_channel: dict[str, str] = {}
        self._user_to_session: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._broadcasts: dict[ChannelType, Callable[[ChannelMessage], Awaitable[None]]] = {}

    def register_channel(self, ch: Channel) -> None:
        ch.bind_gateway(self)
        self._channels[ch.config.channel_id] = ch
        logger.info(f"Channel registered: {ch}")

    async def unregister_channel(self, channel_id: str) -> None:
        async with self._lock:
            ch = self._channels.pop(channel_id, None)
            if ch is None:
                return
            await ch.stop()
            logger.info(f"Channel unregistered: {channel_id}")

            sessions_to_remove = [sid for sid, cid in self._session_to_channel.items() if cid == channel_id]
            for sid in sessions_to_remove:
                self._session_to_channel.pop(sid, None)

    def set_broadcast(
        self,
        ch_type: ChannelType,
        fn: Callable[[ChannelMessage], Awaitable[None]],
    ) -> None:
        """由 WS 客户端连接时调(api/ws.py handle_websocket),把消息广播给前端。
        同一 channel_type 多次连接会覆盖前一个 broadcast fn(WS 端生命周期)。
        """
        self._broadcasts[ch_type] = fn

    async def route_message(self, msg: ChannelMessage) -> None:
        try:
            if not msg.content:
                logger.warning(f"Empty message content from {msg.channel_id}")
                return

            async with self._lock:
                session_id = await self._get_or_create_session(msg)

            await self._safe_add_message(session_id, "user", msg.content)

            try:
                prompt = self._sessions.build_prompt(session_id, msg.content)
                response_text = await self._call_agent(prompt)
            except Exception as e:
                logger.error(f"Agent error for {msg.channel_id}: {e}", exc_info=True)
                await self._send_error(msg, f"处理消息时出错: {e}")
                return

            if not response_text:
                return

            await self._safe_add_message(session_id, "assistant", response_text)

            ch = self._channels.get(msg.channel_id)
            if ch:
                try:
                    await ch.send_message(self._build_response(msg, response_text))
                except Exception as e:
                    logger.error(f"send_message failed for {msg.channel_id}: {e}")

            broadcast = self._broadcasts.get(msg.channel_type)
            if broadcast:
                try:
                    await broadcast(self._build_broadcast(msg, response_text))
                except Exception as e:
                    logger.warning(f"broadcast failed for {msg.channel_type}: {e}")

        except Exception as e:
            logger.error(f"route_message unhandled error: {e}", exc_info=True)
            try:
                await self._send_error(msg, str(e))
            except Exception:
                logger.exception("Even _send_error failed")

    async def _get_or_create_session(self, msg: ChannelMessage) -> str:
        user_key = f"{msg.channel_id}:{msg.user_id}"
        if user_key in self._user_to_session:
            existing = self._user_to_session[user_key]
            try:
                self._sessions.update_session(existing)  # type: ignore[attr-defined]
                return existing
            except Exception:
                pass

        existing_sid = self._sessions.find_latest_session_by_user(  # type: ignore[attr-defined]
            user_id=msg.user_id, channel=msg.channel_type.value
        )
        if existing_sid:
            try:
                if self._sessions.get_session(existing_sid):  # type: ignore[attr-defined]
                    self._user_to_session[user_key] = existing_sid
                    self._session_to_channel[existing_sid] = msg.channel_id
                    logger.info("Resumed session for %s from DB: %s", msg.user_id, existing_sid)
                    return existing_sid
            except Exception:
                pass

        new_sid = msg.session_id or str(uuid.uuid4())
        try:
            title = msg.content[:50] if msg.content else f"{msg.channel_type.value} 会话"
            self._sessions.create_session(  # type: ignore[attr-defined]
                new_sid, title=title, channel=msg.channel_type.value
            )
        except Exception as e:
            logger.error(f"create_session failed for {new_sid}: {e}")
            raise
        self._user_to_session[user_key] = new_sid
        self._session_to_channel[new_sid] = msg.channel_id
        return new_sid

    async def _call_agent(self, prompt: dict[str, Any]) -> str:
        """抽出来的 runner 共用段 (stream_mode='updates' 累积 + 去思考段标签)。"""
        import re

        pieces: list[str] = []
        async for chunk in self._agent.astream({"messages": prompt["messages"]}, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            if "model" in chunk:
                model_data = chunk["model"]
                if model_data and isinstance(model_data, dict):
                    msgs = model_data.get("messages", [])
                    for m in msgs:
                        c = getattr(m, "content", "") or ""
                        if c:
                            pieces.append(c)
        # 首段若仅是"思考 token"(空白 + 单短词 + 空白),且后续还有段,丢弃(避免单段答案被误切)
        if len(pieces) > 1 and re.fullmatch(r"\s*\S+\s*", pieces[0]):
            pieces = pieces[1:]
        full = "".join(pieces)
        # 去思考段标签 + 思考块内容 (<think>... 或未闭合到结尾)
        full = re.sub(r"<think>.*?</think>", "", full, flags=re.DOTALL)
        full = re.sub(r"<think>.*$", "", full, flags=re.DOTALL)
        return full.strip()

    async def _safe_add_message(self, session_id: str, role: str, content: str) -> None:
        try:
            await self._messages.add_message(
                str(uuid.uuid4()),
                session_id,
                role,
                content,
            )
        except Exception as e:
            logger.error(f"add_message failed ({role}): {e}")

    def _build_response(self, orig: ChannelMessage, content: str) -> ChannelMessage:
        return ChannelMessage(
            channel_id=orig.channel_id,
            channel_type=orig.channel_type,
            session_id=orig.session_id,
            user_id=orig.user_id,
            content=content,
            reply_to=orig.id,
            metadata=orig.metadata,
        )

    def _build_broadcast(self, orig: ChannelMessage, content: str) -> ChannelMessage:
        return ChannelMessage(
            channel_id=orig.channel_id,
            channel_type=orig.channel_type,
            session_id=orig.session_id,
            user_id=orig.user_id,
            content=content,
            reply_to=orig.id,
            metadata={**orig.metadata, "broadcast": True},
        )

    async def _send_error(self, orig: ChannelMessage, error: str) -> None:
        try:
            ch = self._channels.get(orig.channel_id)
            if ch:
                err_msg = ChannelMessage(
                    channel_id=orig.channel_id,
                    channel_type=orig.channel_type,
                    session_id=orig.session_id,
                    user_id=orig.user_id,
                    content=error,
                    reply_to=orig.id,
                )
                await ch.send_message(err_msg)
        except Exception as e:
            logger.error(f"_send_error failed: {e}")
