"""REST 鉴权依赖(与 WebSocket 复用同一 token)。

WebSocket 鉴权走两条路径(优先级从高到低):

1. **Sec-WebSocket-Protocol** 子协议头:浏览器原生 ``new WebSocket(url, ['nxv1-<b64u>'])``、
   Rust relay / tokio-tungstenite 都能设,token 不进 URL,不进代理 access log、
   不进浏览器历史、不进错误堆栈。**首选**。
2. **query string ``?token=...``**:旧客户端 / 第三方调试用,默认兼容,
   由 ``NEXUS_WS_AUTH_QUERY_FALLBACK`` 控制开关(默认 ``True``)。下个 major
   版本移除。

两条路径都走 :func:`_hmac_compare` 做常量时间比较,防时序攻击。
"""

from __future__ import annotations

import base64
import binascii
import hmac
import os

from fastapi import HTTPException, Request, WebSocket

from ...config import CONFIG

__all__ = ["_extract_request_token", "_extract_ws_token", "require_token"]


# Sec-WebSocket-Protocol 格式:``nxv1-<base64url(token)>``。
#
# WHY 改前缀(2026-07-12):RFC 7230 §3.2.6 token ABNF 不允许 ``.`` 或 ``=``(两者
# 都是 delimiter,不在 tchar 内),Chromium ≥149 严格校验,旧 ``nexus-v1.token=<value>``
# 形式在 ChatArea mount 时抛 SyntaxError,被 ErrorBoundary 接管。
#
# 修复:短前缀 ``nxv1-``(4+1 chars,``-`` 和字母数字全在 tchar 内) + base64url
# 编码 token(base64url 字符集 ``[A-Za-z0-9-_]``,全在 tchar 内),整个 subprotocol
# 字符串字面合规。Rust 的 HeaderValue 也接受这字符集。
_WS_SUBPROTOCOL_PREFIX = "nxv1-"


def _decode_subprotocol_token(b64u_part: str) -> str | None:
    """把 base64url 段解码回 token;失败返回 None(调用方按无 token 处理)。

    base64url 跟标准 base64 等价但用 ``-`` / ``_`` 替代 ``+`` / ``/``,且末尾
    不带 ``=`` 填充。``base64.urlsafe_b64decode`` 要求显式补齐 padding 到
    4 的倍数,否则抛 ``binascii.Error``。
    """
    if not b64u_part:
        return None
    pad = (-len(b64u_part)) % 4
    try:
        raw = base64.urlsafe_b64decode(b64u_part + ("=" * pad))
    except (binascii.Error, ValueError):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


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
        元素按客户端优先级排序;我们顺序扫描取第一个 ``nxv1-<b64u>``。
    """
    # 1. Sec-WebSocket-Protocol header(RFC 6455 逗号分隔列表)
    header_value = websocket.headers.get("sec-websocket-protocol", "")
    if header_value:
        for proto in header_value.split(","):
            stripped = proto.strip()
            if stripped.startswith(_WS_SUBPROTOCOL_PREFIX):
                token = _decode_subprotocol_token(stripped[len(_WS_SUBPROTOCOL_PREFIX) :])
                if token is not None:
                    return token

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
