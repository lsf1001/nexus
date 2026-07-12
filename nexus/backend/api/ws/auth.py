"""REST 鉴权依赖(与 WebSocket 复用同一 token)。

WebSocket 鉴权走两条路径(优先级从高到低):

1. **Sec-WebSocket-Protocol** 子协议头:浏览器原生 ``new WebSocket(url, ['nexus-v1.token=...'])``、
   Rust relay / tokio-tungstenite 都能设,token 不进 URL,不进代理 access log、
   不进浏览器历史、不进错误堆栈。**首选**。
2. **query string ``?token=...``**:旧客户端 / 第三方调试用,默认兼容,
   由 ``NEXUS_WS_AUTH_QUERY_FALLBACK`` 控制开关(默认 ``True``)。下个 major
   版本移除。

两条路径都走 :func:`_hmac_compare` 做常量时间比较,防时序攻击。
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request, WebSocket

from ...config import CONFIG

__all__ = ["_extract_request_token", "_extract_ws_token", "require_token"]


# Sec-WebSocket-Protocol 格式:``nexus-v1.token=<value>``。
# WHY 命名空间:多协议并存时,subprotocols 字段是 string 数组,
# 不同系统可在同一 WS 端点声明多个 subprotocol 协商;用 ``nexus-v1.`` 前缀
# 避免与其它协议冲突,``.token=`` 后缀让解析无须 split-on-:-then-guess。
_WS_SUBPROTOCOL_PREFIX = "nexus-v1.token="


def _hmac_compare(candidate: str | None, expected: str) -> bool:
    """常量时间 token 比较;candidate 空或 expected 空直接 False。

    用 ``hmac.compare_digest`` 防止长度泄露攻击(Python ``==`` 在长度
    不等时短路,理论上可推算 token 字符)。
    """
    if not expected or not candidate:
        return False
    return hmac.compare_digest(candidate, expected)


def _extract_request_token(request: Request) -> str:
    """从 header / query 提取 token;REST 鉴权用。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "")


def _extract_ws_token(websocket: WebSocket) -> str | None:
    """从 WebSocket 升级请求中提取 token(优先 subprotocol,fallback query)。

    Returns:
        候选 token 字符串;两个路径都拿不到时返回 ``None``。调用方应再走
        :func:`_hmac_compare` 校验。

    Implementation:
        Starlette ``WebSocket`` 没有 ``subprotocols`` 属性,要解析原始
        ``Sec-WebSocket-Protocol`` header。RFC 6455 规定多值用逗号分隔,
        元素按客户端优先级排序;我们顺序扫描取第一个 ``nexus-v1.token=``。
    """
    # 1. Sec-WebSocket-Protocol header(RFC 6455 逗号分隔列表)
    header_value = websocket.headers.get("sec-websocket-protocol", "")
    if header_value:
        for proto in header_value.split(","):
            stripped = proto.strip()
            if stripped.startswith(_WS_SUBPROTOCOL_PREFIX):
                return stripped[len(_WS_SUBPROTOCOL_PREFIX) :]

    # 2. query string fallback(默认开,通过 env 关)
    if os.environ.get("NEXUS_WS_AUTH_QUERY_FALLBACK", "true").lower() == "true":
        token = websocket.query_params.get("token")
        if token:
            return token

    return None


def require_token(request: Request) -> None:
    """FastAPI 依赖:校验 REST 请求 token。失败抛 401。"""
    token = _extract_request_token(request)
    expected = CONFIG.get("ws_token", "")
    if not _hmac_compare(token, expected):
        raise HTTPException(status_code=401, detail="未授权")
