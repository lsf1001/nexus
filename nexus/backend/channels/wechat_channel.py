"""微信通道核心类：长轮询 / 消息收发 / 状态管理。

从 wechat.py 拆分（2026-06-13 P0 重构）。WeChatChannel 负责：
- 启动时加载账号、恢复 context tokens、通知服务器
- 后台长轮询 getupdates 任务
- 接收消息后调用 on_message 回调
- 错误码 -14 (session 过期) 走 Session Guard 暂停通道
- 二维码图片生成（静态工具方法）

依赖：wechat_api / wechat_account / wechat_tokens / wechat_protocol / wechat_state / wechat_types / base
"""

from __future__ import annotations

import asyncio
import io
import logging

import httpx

from .base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from .wechat_account import (
    _get_state_dir,
    _list_indexed_weixin_account_ids,
    _load_account,
    _normalize_account_id,
)
from .wechat_api import _send_message
from .wechat_protocol import _build_base_info, _build_headers
from .wechat_tokens import _get_context_token, _restore_context_tokens, _save_context_tokens, _set_context_token
from .wechat_types import FIXED_BASE_URL, MessageItemType, WeixinAccount

logger = logging.getLogger(__name__)

# 长轮询参数
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
DEFAULT_CONFIG_TIMEOUT_MS = 10_000

# Session Guard (OpenClaw 兼容)
# 错误码 -14 表示 session 过期，暂停 1 小时
SESSION_EXPIRED_ERRCODE = -14
SESSION_PAUSE_DURATION_MS = 60 * 60 * 1000  # 1 小时
_pause_until_map: dict[str, float] = {}


def _pause_session(account_id: str) -> None:
    """暂停 session 至 1 小时后。"""
    _pause_until_map[account_id] = asyncio.get_event_loop().time() + SESSION_PAUSE_DURATION_MS / 1000


def _is_session_paused(account_id: str) -> bool:
    """检查 session 是否处于暂停状态。"""
    deadline = _pause_until_map.get(account_id)
    if deadline is None:
        return False
    if asyncio.get_event_loop().time() >= deadline:
        del _pause_until_map[account_id]
        return False
    return True


def _get_remaining_pause_ms(account_id: str) -> float:
    """获取 session 剩余暂停时间（毫秒）。"""
    deadline = _pause_until_map.get(account_id)
    if deadline is None:
        return 0.0
    remaining = deadline - asyncio.get_event_loop().time()
    return max(0.0, remaining * 1000)


# ========== WeChatChannel 类 ==========


class WeChatChannel(Channel):
    """微信通道"""

    def __init__(self, config: ChannelConfig, token: str = ""):
        super().__init__(config)
        self.token = token
        self._http_client: httpx.AsyncClient | None = None
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._account: WeixinAccount | None = None
        self._get_updates_buf: str = ""
        self._on_message_callback = None

    @property
    def base_url(self) -> str:
        if self._account and self._account.base_url:
            return self._account.base_url
        return FIXED_BASE_URL

    async def start(self) -> None:
        """启动微信通道"""
        logger.debug(f"WeChatChannel.start() called with token={self.token[:20] if self.token else 'None'}...")
        self._update_state(status=ChannelStatus.STARTING)

        # 加载账号
        if self.token:
            # 检查 token 是 account_id 还是 bot_token
            normalized_id = _normalize_account_id(self.token)
            logger.debug(f"start: normalized_id={normalized_id}")
            existing_account = _load_account(normalized_id)
            logger.debug(f"start: existing_account loaded: {existing_account is not None}")

            if existing_account:
                # token 是 account_id，直接加载
                self._account = existing_account
            elif self.token and "@" in self.token:
                # token 是 bot_token 格式 (如 2472693b153c@im.bot:xxx)
                # 需要从所有账号中搜索匹配的 token
                for acc_id in _list_indexed_weixin_account_ids():
                    acc = _load_account(acc_id)
                    if acc and acc.token == self.token:
                        self._account = acc
                        self.token = acc_id  # 更新为正确的 account_id
                        break

            if self._account:
                _restore_context_tokens(self._account.account_id)
                # 加载 sync buffer
                sync_file = _get_state_dir() / "accounts" / f"{self._account.account_id}.sync.buf"
                if sync_file.exists():
                    self._get_updates_buf = sync_file.read_text()

        if not self._account:
            logger.warning("WeChat channel started without account")

        # 通知服务器启动
        self._http_client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=_build_headers(self._account.token if self._account else None),
            timeout=30.0,
        )

        try:
            body = {"base_info": _build_base_info()}
            resp = await self._http_client.post("/ilink/bot/msg/notifystart", json=body)
            logger.info(f"notifyStart response: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"notifyStart failed: {e}")

        self._running = True
        self._update_state(status=ChannelStatus.RUNNING, started_at=None)

        # 启动长轮询
        self._poll_task = asyncio.create_task(self._poll_messages())
        logger.info(f"WeChat Channel {self.config.channel_id} started")

    async def stop(self) -> None:
        """停止微信通道"""
        self._update_state(status=ChannelStatus.STOPPING)
        self._running = False

        if self._http_client and self._account:
            try:
                body = {"base_info": _build_base_info()}
                await self._http_client.post("/ilink/bot/msg/notifystop", json=body)
            except Exception as e:
                logger.warn(f"notifyStop failed: {e}")

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._http_client:
            await self._http_client.aclose()

        self._update_state(status=ChannelStatus.STOPPED)
        logger.info(f"WeChat Channel {self.config.channel_id} stopped")

    async def send_message(self, message: ChannelMessage) -> None:
        """发送消息"""
        if not self._http_client or not self._account:
            logger.error("Channel not properly initialized")
            return

        context_token = _get_context_token(self._account.account_id, message.user_id)

        try:
            await _send_message(
                self.base_url,
                self._account.token,
                message.user_id,
                message.content,
                context_token,
            )
            logger.debug(f"Message sent to {message.user_id}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def _poll_messages(self) -> None:
        """长轮询获取消息 (OpenClaw 兼容)"""
        logger.info(
            f"WeChat _poll_messages STARTED for account_id={self._account.account_id if self._account else 'unknown'}"
        )
        poll_interval = 1.0
        account_id = self._account.account_id if self._account else "unknown"

        while self._running:
            try:
                logger.info(f"Polling loop iteration, running={self._running}")
                if not self._http_client or not self._account:
                    await asyncio.sleep(poll_interval)
                    continue

                # 检查 session 是否暂停
                if _is_session_paused(account_id):
                    remaining_min = int(_get_remaining_pause_ms(account_id) / 60000)
                    logger.info(f"session paused for {remaining_min} min, waiting...")
                    await asyncio.sleep(_get_remaining_pause_ms(account_id) / 1000)
                    continue

                body = {
                    "get_updates_buf": self._get_updates_buf or "",
                    "base_info": _build_base_info(),
                }

                try:
                    response = await self._http_client.post(
                        "/ilink/bot/getupdates",
                        json=body,
                        timeout=DEFAULT_LONG_POLL_TIMEOUT_MS / 1000,
                    )
                    logger.info(f"getUpdates response: status={response.status_code}")
                    if response.status_code == 200:
                        data = response.json()
                        ret = data.get("ret", 0)
                        errcode = data.get("errcode", 0)
                        msgs_count = len(data.get("msgs", []))
                        logger.info(f"getUpdates: ret={ret}, errcode={errcode}, msgs={msgs_count}")

                        if ret == 0 or errcode == 0:
                            msgs = data.get("msgs", [])
                            for raw_msg in msgs:
                                await self._handle_incoming_message(raw_msg)

                            if data.get("get_updates_buf"):
                                self._get_updates_buf = data["get_updates_buf"]
                                sync_file = _get_state_dir() / "accounts" / f"{self._account.account_id}.sync.buf"
                                sync_file.parent.mkdir(parents=True, exist_ok=True)
                                sync_file.write_text(self._get_updates_buf)

                            if data.get("longpolling_timeout_ms", 0) > 0:
                                poll_interval = data["longpolling_timeout_ms"] / 1000
                            else:
                                poll_interval = 1.0
                        elif errcode == SESSION_EXPIRED_ERRCODE:
                            _pause_session(account_id)
                            remaining_min = int(_get_remaining_pause_ms(account_id) / 60000)
                            logger.warn(f"Session expired (errcode={errcode}), pausing for {remaining_min} min")
                            await asyncio.sleep(5)
                        else:
                            logger.warning(f"getUpdates errcode={errcode}")
                            await asyncio.sleep(poll_interval)
                    else:
                        logger.warning(f"getUpdates returned {response.status_code}")
                        await asyncio.sleep(poll_interval)
                except Exception as e:
                    logger.error(f"getUpdates error: {e}")
                    await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poll error: {e}")
                await asyncio.sleep(poll_interval)

    async def _handle_incoming_message(self, raw_msg: dict) -> None:
        """处理收到的消息"""
        try:
            from_user = raw_msg.get("from_user_id", "")
            content = self._extract_content(raw_msg)
            context_token = raw_msg.get("context_token")

            logger.debug(f"WeChat incoming message: from={from_user}, content={content[:50]}...")

            if context_token and from_user:
                _set_context_token(self._account.account_id, from_user, context_token)
                _save_context_tokens(self._account.account_id)

            msg_type = self._get_message_type(raw_msg)

            channel_msg = ChannelMessage(
                channel_id=self.config.channel_id,
                channel_type=ChannelType.WECHAT,
                session_id=f"wechat:{from_user}",
                user_id=from_user,
                content=content,
                message_type=msg_type,
                raw_data=raw_msg,
                reply_to=context_token,
            )

            # 如果有回调，直接调用（用于 WebSocket 转发到前端）
            if self._on_message_callback:
                logger.debug(f"Calling callback for message from {from_user}")
                self._on_message_callback(channel_msg)
            else:
                logger.warning(
                    f"No callback set! Channel id={self.config.channel_id}, callback={self._on_message_callback}"
                )
                await self._safe_handle_message(channel_msg)
        except Exception as e:
            logger.error(f"Error handling incoming message: {e}")

    def on_message(self, callback) -> None:
        """设置消息回调"""
        self._on_message_callback = callback

    def _get_message_type(self, raw: dict) -> MessageType:
        """获取消息类型"""
        item_list = raw.get("item_list", [])
        if not item_list:
            return MessageType.TEXT

        first_item = item_list[0]
        item_type = first_item.get("type", 1)

        type_map = {
            1: MessageType.TEXT,
            2: MessageType.IMAGE,
            3: MessageType.VOICE,
            4: MessageType.FILE,
            5: MessageType.VIDEO,
        }
        return type_map.get(item_type, MessageType.TEXT)

    def _extract_content(self, raw: dict) -> str:
        """提取文本内容"""
        item_list = raw.get("item_list", [])
        for item in item_list:
            if item.get("type") == MessageItemType.TEXT:
                text = item.get("text_item", {}).get("text", "")
                if text:
                    return text
            elif item.get("type") == MessageItemType.VOICE:
                voice_text = item.get("voice_item", {}).get("text")
                if voice_text:
                    return voice_text
        return ""

    @staticmethod
    def generate_qrcode_image(qrcode_url: str) -> bytes:
        """生成二维码图片"""
        try:
            import qrcode

            img = qrcode.make(qrcode_url)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            return b""
