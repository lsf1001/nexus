"""微信通道 HTTP API 客户端。

从 wechat.py 拆分（2026-06-13 P0 重构）。包含：
- 通用 HTTP 封装：_api_get_fetch / _api_post_fetch
- 业务级 API：_get_config / _send_typing / _send_message
"""

from __future__ import annotations

import json

import httpx

from .wechat_protocol import _build_base_info, _build_headers, _generate_client_id, _random_wechat_uin
from .wechat_types import MessageItemType, MessageState, MessageTypeEnum


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


# ========== 业务级 API ==========


async def _get_config(base_url: str, token: str, ilink_user_id: str, context_token: str = "") -> dict:
    """获取用户配置（包括 typing_ticket）"""
    body = {
        "ilink_user_id": ilink_user_id,
        "context_token": context_token,
        "base_info": _build_base_info(),
    }
    raw = await _api_post_fetch(base_url, "/ilink/bot/getconfig", body, token, 10_000)
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
    raw = await _api_post_fetch(base_url, "/ilink/bot/sendtyping", body, token, 10_000)
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
    await _api_post_fetch(base_url, "/ilink/bot/sendmessage", body, token, 15_000)
    return client_id
