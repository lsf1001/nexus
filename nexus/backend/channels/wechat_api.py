"""微信通道 HTTP API 客户端。

从 wechat.py 拆分（2026-06-13 P0 重构）。纯异步 HTTP 封装（GET / POST），
不持有状态，只被登录 / 发送消息等业务流程调用。
"""
from __future__ import annotations

import httpx

from .wechat_protocol import _build_headers, _random_wechat_uin


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
