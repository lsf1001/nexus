"""WebSocket Sec-WebSocket-Protocol 鉴权测试。

覆盖:
  1. 客户端用 subprotocol ``nxv1-<base64url(token)>`` → 握手成功,服务端 echo subprotocol
  2. 客户端用 subprotocol 但 token 错 → 握手失败 close 4001
  3. 客户端用 subprotocol 缺失 token 值 → 走 query fallback
  4. ``NEXUS_WS_AUTH_QUERY_FALLBACK=false`` → 关闭 query,纯 subprotocol
  5. 空 expected token → 任意客户端都被拒(防止默认 token 被错配)
  6. subprotocol 多值(含其它协议) → 正确解析 nxv1-<b64u>
"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from nexus.backend.main import app


def _b64u_subprotocol(token: str) -> str:
    """生成 ``nxv1-<base64url(token)>`` 字符串(测试 helper)。

    WHY helper:2026-07-12 改前缀后,每个用例都要写同一拼装逻辑。集中到
    一个函数,base64 padding / 字符替换不会在 8 个测试里漂移。
    """
    b64u = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    return f"nxv1-{b64u}"


def _authed_token(monkeypatch) -> str:
    """注入 ws_token(同 test_ws_resilience)。

    WHY 也开 ``NEXUS_WS_AUTH_QUERY_FALLBACK=true``: spec §3 P0-1 把默认
    改为 OFF,但本文件含 query fallback 集成测试(``test_ws_query_fallback_when_no_subprotocol``
    / ``test_ws_subprotocol_takes_priority_over_query``)需要 fallback 开启
    才能验证;显式开 false 的测试会自己 override。
    """
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    monkeypatch.setenv("NEXUS_WS_AUTH_QUERY_FALLBACK", "true")
    return "test-token"


def test_ws_subprotocol_token_accepted(monkeypatch) -> None:
    """subprotocol token 合法 → 握手成功。"""
    _authed_token(monkeypatch)
    expected = _b64u_subprotocol("test-token")

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/ws",
            subprotocols=[expected],
        ) as ws:
            # 服务端必须 echo 客户端发的完整 nxv1-<b64u> 字符串,
            # 不是截短的 'nxv1'(RFC 6455 §1.9)
            assert ws.accepted_subprotocol == expected, (
                f"server should echo full subprotocol, got {ws.accepted_subprotocol!r}"
            )
            ws.send_json({"content": "ping", "title": "subprotocol-test"})
            # 立即 close,只验证握手路径
            ws.close()


def test_ws_subprotocol_token_wrong_rejected(monkeypatch) -> None:
    """subprotocol token 错 → close 4001。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/ws",
                subprotocols=[_b64u_subprotocol("wrong-token")],
            ) as ws:
                ws.receive_json()  # 不应到达


def test_ws_subprotocol_takes_priority_over_query(monkeypatch) -> None:
    """subprotocol 与 query 同时存在 → subprotocol 优先(若 query 是错的而 subprotocol 对,仍 OK)。"""
    _authed_token(monkeypatch)
    expected = _b64u_subprotocol("test-token")

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/ws?token=garbage",
            subprotocols=[expected],
        ) as ws:
            assert ws.accepted_subprotocol == expected, (
                f"server should echo full subprotocol, got {ws.accepted_subprotocol!r}"
            )
            ws.close()


def test_ws_query_fallback_when_no_subprotocol(monkeypatch) -> None:
    """未设 subprotocol → 走 query fallback。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws?token=test-token") as ws:
            # fallback 路径不选 subprotocol
            assert ws.accepted_subprotocol is None
            ws.close()


def test_ws_query_rejected_when_env_unset(monkeypatch) -> None:
    """env 完全未设时,端到端 WS 握手必须被拒(P0-1 核心默认行为锁定)。

    WHY: spec §3 P0-1 把 NEXUS_WS_AUTH_QUERY_FALLBACK 默认改 false。本测试
    不依赖子模块 _is_query_fallback_enabled() 单测,而是走 HTTP upgrade 真实
    握手路径,防有人在 main.py::websocket_endpoint 链路里硬编码开 fallback
    把默认态绕过去。query token 是错的也无关 —— 任何 query 都应被拒。
    """
    import pytest
    from starlette.websockets import WebSocketDisconnect

    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    monkeypatch.delenv("NEXUS_WS_AUTH_QUERY_FALLBACK", raising=False)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/ws?token=any-value") as ws:
                ws.receive_json()


def test_ws_query_fallback_disabled_via_env(monkeypatch) -> None:
    """``NEXUS_WS_AUTH_QUERY_FALLBACK=false`` 时,query token 被拒。"""
    _authed_token(monkeypatch)
    monkeypatch.setenv("NEXUS_WS_AUTH_QUERY_FALLBACK", "false")

    with TestClient(app) as client:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.receive_json()


def test_ws_no_token_at_all_rejected(monkeypatch) -> None:
    """既无 subprotocol 也无 query → 拒绝。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/ws") as ws:
                ws.receive_json()


def test_ws_empty_expected_token_rejects_all(monkeypatch) -> None:
    """``ws_token=''`` 配置时,任何客户端都被拒(防止默认 token 误配)。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "")

    with TestClient(app) as client:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        # 即使客户端带合法形式,空 expected 也直接拒
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/ws",
                subprotocols=[_b64u_subprotocol("anything")],
            ) as ws:
                ws.receive_json()


def test_ws_subprotocol_multiple_values_parses_nexus(monkeypatch) -> None:
    """subprotocol 含多个值(包括其它协议),正确解析 nxv1-<b64u>。"""
    _authed_token(monkeypatch)
    expected = _b64u_subprotocol("test-token")

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/ws",
            subprotocols=["graphql-ws", expected],
        ) as ws:
            # 服务端 next() 取第一个 nxv1-* 完整字符串 echo 回去
            assert ws.accepted_subprotocol == expected, (
                f"server should echo full subprotocol, got {ws.accepted_subprotocol!r}"
            )
            ws.close()


def test_ws_subprotocol_malformed_value_rejected(monkeypatch) -> None:
    """subprotocol 存在但格式错误(非 nxv1-)→ 走 query 或拒绝。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        # 错误前缀,解析不出 token,fallback 也无 query → 拒
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/ws",
                subprotocols=["malformed-protocol"],
            ) as ws:
                ws.receive_json()
