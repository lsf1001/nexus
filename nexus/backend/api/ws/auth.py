"""REST 鉴权依赖(与 WebSocket 复用同一 token)。

模块化拆分后,``api/ws.py`` 仍 re-export :func:`require_token`,
``main.py`` 用 ``Depends(require_token)`` 挂 REST 路由。
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ...config import CONFIG

__all__ = ["_extract_request_token", "require_token"]


def _extract_request_token(request: Request) -> str:
    """从 header / query 提取 token;REST 鉴权用。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "")


def require_token(request: Request) -> None:
    """FastAPI 依赖:校验 REST 请求 token。失败抛 401。"""
    token = _extract_request_token(request)
    expected = CONFIG.get("ws_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="未授权")
