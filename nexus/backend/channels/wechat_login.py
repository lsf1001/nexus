"""微信通道 QR 登录流程。

从 wechat.py 拆分（2026-06-13 P0 重构）。包含：
- 二维码拉取 / 状态轮询（_fetch_qrcode / _poll_qr_status）
- 登录会话生命周期（_is_login_fresh / _purge_expired_logins / _get_local_bot_token_list）
- 公开 API：wechat_qr_login / wait_qr_scan
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from ..main import _handle_wechat_message  # noqa: F401  保持语义
from .base import ChannelConfig, ChannelType
from .wechat_account import (
    _list_indexed_weixin_account_ids,
    _load_account,
    _normalize_account_id,
    _register_weixin_account_id,
    _save_account,
)
from .wechat_api import _api_get_fetch, _api_post_fetch
from .wechat_state import _accounts, _active_logins, _global_lock
from .wechat_types import FIXED_BASE_URL, QRSession, WeixinAccount

logger = logging.getLogger(__name__)

# 复用 wechat.py 的常量
DEFAULT_ILINK_BOT_TYPE = "3"
QR_LONG_POLL_TIMEOUT_MS = 35_000
ACTIVE_LOGIN_TTL_MS = 5 * 60 * 1000
DEFAULT_CONFIG_TIMEOUT_MS = 10_000


# ========== QR 拉取与轮询 ==========


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


# ========== 公开 API：QR 登录 ==========


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
                from .wechat_channel import WeChatChannel as WCH  # noqa: N814

                _active_channel = WCH(config, token=normalized_id)
                await _active_channel.start()

                # 立即设置消息回调
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
