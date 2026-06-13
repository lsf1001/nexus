"""微信通道 - 原生实现直接接入微信服务器。

参考 @tencent-weixin/openclaw-weixin 插件的完整实现，不依赖 OpenClaw。

P0 重构（2026-06-13）：数据类型定义（WeixinAccount / QRSession / MessageItemType 等）已移至
wechat_types.py，本文件保留业务逻辑、账号管理、API 通信、登录流程、Channel 实现。
"""

import asyncio
import base64
import io
import json
import logging
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from .base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelStatus,
    ChannelType,
    MessageType,
)
from .wechat_state import (
    _accounts,  # noqa: F401  保留 re-export
    _active_channel,  # noqa: F401  保留 re-export
    _active_logins,  # noqa: F401  保留 re-export
    _context_tokens,  # noqa: F401  保留 re-export
    _global_lock,
)
from .wechat_types import (
    FIXED_BASE_URL,  # noqa: F401  保留 re-export 兼容旧导入
    MessageItemType,  # noqa: F401  保留 re-export
    MessageState,  # noqa: F401  保留 re-export
    MessageTypeEnum,  # noqa: F401  保留 re-export
    QRSession,
    WeixinAccount,
)
from .wechat_protocol import (
    _build_base_info,  # noqa: F401  保留 re-export
    _build_client_version,  # noqa: F401  保留 re-export
    _build_headers,  # noqa: F401  保留 re-export
    _generate_client_id,  # noqa: F401  保留 re-export
    _random_wechat_uin,  # noqa: F401  保留 re-export
)
from .wechat_account import (
    _check_token_valid,  # noqa: F401  保留 re-export
    _delete_account,  # noqa: F401  保留 re-export
    _get_state_dir,  # noqa: F401  保留 re-export
    _list_indexed_weixin_account_ids,  # noqa: F401  保留 re-export
    _load_account,  # noqa: F401  保留 re-export
    _normalize_account_id,  # noqa: F401  保留 re-export
    _register_weixin_account_id,  # noqa: F401  保留 re-export
    _resolve_account_file_path,  # noqa: F401  保留 re-export
    _resolve_account_index_path,  # noqa: F401  保留 re-export
    _resolve_context_token_file_path,  # noqa: F401  保留 re-export
    _save_account,  # noqa: F401  保留 re-export
)

logger = logging.getLogger(__name__)

# 常量
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
DEFAULT_CONFIG_TIMEOUT_MS = 10_000
CHANNEL_VERSION = "2.4.4"
DEFAULT_ILINK_BOT_TYPE = "3"
QR_LONG_POLL_TIMEOUT_MS = 35_000
ACTIVE_LOGIN_TTL_MS = 5 * 60 * 1000


# ========== 账号管理 ==========
# （WeixinAccount / QRSession 数据类已移至 wechat_types.py）


# 全局状态（带线程锁保护）已移至 wechat_state.py


def get_active_wechat_channel():
    """获取当前活跃的微信通道"""
    return _active_channel


def _set_active_channel(channel: "WeChatChannel") -> None:
    """设置当前活跃的微信通道"""
    global _active_channel
    _active_channel = channel


def _clear_active_channel() -> None:
    """清除当前活跃的微信通道"""
    global _active_channel
    _active_channel = None


# ========== 账号管理业务函数（增删改查 / 路径 / 归一化）已移至 wechat_account.py ==========


def _save_context_tokens(account_id: str) -> None:
    """保存 context tokens 到磁盘"""
    file_path = _resolve_context_token_file_path(account_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tokens = {}
    prefix = f"{account_id}:"
    for k, v in _context_tokens.items():
        if k.startswith(prefix):
            tokens[k[len(prefix) :]] = v
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False)


def _restore_context_tokens(account_id: str) -> None:
    """从磁盘恢复 context tokens"""
    file_path = _resolve_context_token_file_path(account_id)
    if not file_path.exists():
        return
    try:
        with open(file_path, encoding="utf-8") as f:
            tokens = json.load(f)
        for user_id, token in tokens.items():
            _context_tokens[f"{account_id}:{user_id}"] = token
        logger.info(f"Restored {len(tokens)} context tokens for account={account_id}")
    except Exception as e:
        logger.warn(f"Failed to restore context tokens: {e}")


def _set_context_token(account_id: str, user_id: str, token: str) -> None:
    """设置 context token"""
    key = f"{account_id}:{user_id}"
    _context_tokens[key] = token


def _get_context_token(account_id: str, user_id: str) -> str | None:
    """获取 context token"""
    return _context_tokens.get(f"{account_id}:{user_id}")


# ========== 协议层（ID / 头 / base_info）已移至 wechat_protocol.py ==========


# ========== API 调用 ==========


async def _api_get_fetch(base_url: str, endpoint: str, timeout_ms: int = 15000) -> str:
    """GET 请求"""
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_wechat_uin(),
    }
    async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
        response = await client.get(url, headers=headers)
        if not response.is_success:
            raise Exception(f"GET {url} failed: {response.status_code}")
        return response.text


async def _api_post_fetch(
    base_url: str, endpoint: str, body: dict, token: str | None = None, timeout_ms: int = 15000
) -> str:
    """POST JSON 请求"""
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = _build_headers(token)
    async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
        response = await client.post(url, json=body, headers=headers)
        if not response.is_success:
            raise Exception(f"POST {url} failed: {response.status_code}")
        return response.text


async def _fetch_qrcode(api_base_url: str, bot_type: str = DEFAULT_ILINK_BOT_TYPE) -> dict:
    """获取二维码"""
    local_token_list = _get_local_bot_token_list()
    raw = await _api_post_fetch(
        api_base_url,
        f"/ilink/bot/get_bot_qrcode?bot_type={bot_type}",
        body={"local_token_list": local_token_list},
        timeout_ms=30000,
    )
    return json.loads(raw)


async def _poll_qr_status(api_base_url: str, qrcode: str, verify_code: str = "") -> dict:
    """轮询二维码状态"""
    endpoint = f"/ilink/bot/get_qrcode_status?qrcode={qrcode}"
    if verify_code:
        endpoint += f"&verify_code={verify_code}"
    try:
        raw = await _api_get_fetch(api_base_url, endpoint, timeout_ms=QR_LONG_POLL_TIMEOUT_MS)
        return json.loads(raw)
    except Exception as e:
        if "AbortError" in str(e) or "timeout" in str(e).lower():
            return {"status": "wait"}
        raise


def _get_local_bot_token_list() -> list[str]:
    """获取本地已登录账号的 token 列表"""
    tokens = []
    for account_id in _list_indexed_weixin_account_ids():
        data = _load_account(account_id)
        if data and data.token:
            tokens.append(data.token)
    return tokens[:10]


def _is_login_fresh(login: QRSession) -> bool:
    """检查会话是否新鲜"""
    return time.time() - login.started_at < ACTIVE_LOGIN_TTL_MS


def _purge_expired_logins() -> None:
    """清理过期的登录会话"""
    with _global_lock:
        for sid in list(_active_logins.keys()):
            if not _is_login_fresh(_active_logins[sid]):
                del _active_logins[sid]


# ========== 消息类型定义 ==========
# （MessageItemType / MessageTypeEnum / MessageState 已移至 wechat_types.py）


# ========== 消息发送 ==========


async def _get_config(base_url: str, token: str, ilink_user_id: str, context_token: str = "") -> dict:
    """获取用户配置（包括 typing_ticket）"""
    body = {
        "ilink_user_id": ilink_user_id,
        "context_token": context_token,
        "base_info": _build_base_info(),
    }
    raw = await _api_post_fetch(base_url, "/ilink/bot/getconfig", body, token, DEFAULT_CONFIG_TIMEOUT_MS)
    return json.loads(raw)


async def _send_typing(
    base_url: str, token: str, to_user: str, typing_ticket: str = "", context_token: str = ""
) -> str:
    """发送正在输入状态"""
    # 如果没有 typing_ticket，先获取
    if not typing_ticket:
        try:
            config = await _get_config(base_url, token, to_user, context_token)
            typing_ticket = config.get("typing_ticket", "")
        except Exception:
            typing_ticket = ""

    body = {
        "ilink_user_id": to_user,
        "typing_ticket": typing_ticket,
        "status": 1,  # 1=typing
        "base_info": _build_base_info(),
    }
    raw = await _api_post_fetch(base_url, "/ilink/bot/sendtyping", body, token, DEFAULT_CONFIG_TIMEOUT_MS)
    return raw


async def _send_message(base_url: str, token: str, to_user: str, text: str, context_token: str | None = None) -> str:
    """发送文本消息"""
    client_id = _generate_client_id()
    item_list = [{"type": MessageItemType.TEXT, "text_item": {"text": text}}]
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user,
            "client_id": client_id,
            "message_type": MessageTypeEnum.BOT,
            "message_state": MessageState.FINISH,
            "item_list": item_list,
            "context_token": context_token,
        },
        "base_info": _build_base_info(),
    }
    await _api_post_fetch(base_url, "/ilink/bot/sendmessage", body, token, DEFAULT_API_TIMEOUT_MS)
    return client_id


# ========== 独立 QR 登录流程 ==========


async def wechat_qr_login() -> dict:
    """启动 QR 登录流程"""
    session_key = str(uuid.uuid4())
    _purge_expired_logins()

    try:
        data = await _fetch_qrcode(FIXED_BASE_URL, DEFAULT_ILINK_BOT_TYPE)
        qrcode = data.get("qrcode", "")
        qrcode_url = data.get("qrcode_img_content", "")

        session = QRSession(
            session_key=session_key,
            qrcode=qrcode,
            qrcode_url=qrcode_url,
        )
        with _global_lock:
            _active_logins[session_key] = session

        return {
            "qrcode_url": qrcode_url,
            "qrcode": qrcode,
            "session_key": session_key,
        }
    except Exception as e:
        logger.error(f"QR login failed: {e}")
        return {"error": str(e)}


async def wait_qr_scan(session_key: str, timeout_ms: int = 480000) -> dict:
    """等待二维码扫描"""
    with _global_lock:
        session = _active_logins.get(session_key)
    if not session:
        return {"connected": False, "message": "No active login session"}

    with _global_lock:
        if not _is_login_fresh(session):
            del _active_logins[session_key]
            return {"connected": False, "message": "QR code expired, please get a new one"}

    deadline = time.time() + timeout_ms / 1000
    refresh_count = 0
    max_refresh = 3

    while time.time() < deadline:
        try:
            data = await _poll_qr_status(
                session.current_api_base_url, session.qrcode, session.pending_verify_code or ""
            )
            status = data.get("status", "wait")
            with _global_lock:
                session.status = status

            if status == "wait":
                await asyncio.sleep(1)
            elif status == "confirmed":
                bot_token = data.get("bot_token", "")
                ilink_bot_id = data.get("ilink_bot_id", "")
                ilink_user_id = data.get("ilink_user_id", "")
                base_url = data.get("baseurl", "") or FIXED_BASE_URL

                if not ilink_bot_id:
                    return {"connected": False, "message": "Login confirmed but ilink_bot_id missing"}

                normalized_id = _normalize_account_id(ilink_bot_id)
                account = WeixinAccount(
                    account_id=normalized_id,
                    user_id=ilink_user_id or "",
                    token=bot_token,
                    base_url=base_url,
                )
                with _global_lock:
                    _accounts[normalized_id] = account
                _save_account(account)
                _register_weixin_account_id(normalized_id)

                # 创建微信通道并启动
                global _active_channel
                config = ChannelConfig(
                    channel_id=f"wechat:{normalized_id}",
                    channel_type=ChannelType.WECHAT,
                    name=f"WeChat ({normalized_id[:8]}...)",
                    settings={"account_id": normalized_id},
                )
                from .wechat import WeChatChannel as WCH  # noqa: N814

                _active_channel = WCH(config, token=normalized_id)
                await _active_channel.start()

                # 立即设置消息回调
                from nexus.backend.main import _handle_wechat_message

                _active_channel.on_message(_handle_wechat_message)
                logger.info(f"Callback set for channel {_active_channel.config.channel_id}")

                with _global_lock:
                    del _active_logins[session_key]

                return {
                    "connected": True,
                    "bot_token": bot_token,
                    "account_id": normalized_id,
                    "user_id": ilink_user_id,
                    "base_url": base_url,
                    "message": "Login successful",
                }
            elif status == "expired":
                refresh_count += 1
                if refresh_count > max_refresh:
                    with _global_lock:
                        del _active_logins[session_key]
                    return {"connected": False, "message": "QR code expired multiple times"}
                await asyncio.sleep(1)
            elif status == "need_verifycode":
                # 需要输入验证码（暂时不支持交互式输入）
                await asyncio.sleep(1)
            elif status == "scaned_but_redirect":
                redirect_host = data.get("redirect_host")
                if redirect_host:
                    session.current_api_base_url = f"https://{redirect_host}"
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Poll error: {e}")
            await asyncio.sleep(1)

    del _active_logins[session_key]
    return {"connected": False, "message": "Login timeout"}


# ========== Session Guard (OpenClaw 兼容) ==========
# 错误码 -14 表示 session 过期，暂停 1 小时

SESSION_EXPIRED_ERRCODE = -14
SESSION_PAUSE_DURATION_MS = 60 * 60 * 1000  # 1 小时
_pause_until_map: dict[str, float] = {}


def _pause_session(account_id: str) -> None:
    """暂停会话 1 小时"""
    until = time.time() + SESSION_PAUSE_DURATION_MS / 1000
    _pause_until_map[account_id] = until
    logger.debug(f"session-guard: paused accountId={account_id} until={time.ctime(until)}")


def _is_session_paused(account_id: str) -> bool:
    """检查会话是否暂停"""
    until = _pause_until_map.get(account_id)
    if until is None:
        return False
    if time.time() >= until:
        del _pause_until_map[account_id]
        return False
    return True


def _get_remaining_pause_ms(account_id: str) -> float:
    """获取剩余暂停时间（毫秒）"""
    until = _pause_until_map.get(account_id)
    if until is None:
        return 0
    remaining = (until - time.time()) * 1000
    if remaining <= 0:
        del _pause_until_map[account_id]
        return 0
    return remaining


# ========== WeChatChannel 实现 ==========


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
