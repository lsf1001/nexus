"""WebSocket Sec-WebSocket-Protocol 鉴权测试。

覆盖:
  1. 客户端用 subprotocol ``nexus-v1.token=<value>`` → 握手成功,服务端 echo subprotocol
  2. 客户端用 subprotocol 但 token 错 → 握手失败 close 4001
  3. 客户端用 subprotocol 缺失 token 值 → 走 query fallback
  4. ``NEXUS_WS_AUTH_QUERY_FALLBACK=false`` → 关闭 query,纯 subprotocol
  5. 空 expected token → 任意客户端都被拒(防止默认 token 被错配)
  6. subprotocol 多值(含其它协议) → 正确解析 nexus-v1.token=
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from nexus.backend.main import app


def _authed_token(monkeypatch) -> str:
    """注入 ws_token(同 test_ws_resilience)。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    return "test-token"


def test_ws_subprotocol_token_accepted(monkeypatch) -> None:
    """subprotocol token 合法 → 握手成功。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/ws",
            subprotocols=["nexus-v1.token=test-token"],
        ) as ws:
            # subprotocol 已协商;客户端应能收到 ws 服务端的 subprotocol
            assert ws.accepted_subprotocol == "nexus-v1"
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
                subprotocols=["nexus-v1.token=wrong-token"],
            ) as ws:
                ws.receive_json()  # 不应到达


def test_ws_subprotocol_takes_priority_over_query(monkeypatch) -> None:
    """subprotocol 与 query 同时存在 → subprotocol 优先(若 query 是错的而 subprotocol 对,仍 OK)。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/ws?token=garbage",
            subprotocols=["nexus-v1.token=test-token"],
        ) as ws:
            assert ws.accepted_subprotocol == "nexus-v1"
            ws.close()


def test_ws_query_fallback_when_no_subprotocol(monkeypatch) -> None:
    """未设 subprotocol → 走 query fallback。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws?token=test-token") as ws:
            # fallback 路径不选 subprotocol
            assert ws.accepted_subprotocol is None
            ws.close()


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
                subprotocols=["nexus-v1.token=anything"],
            ) as ws:
                ws.receive_json()


def test_ws_subprotocol_multiple_values_parses_nexus(monkeypatch) -> None:
    """subprotocol 含多个值(包括其它协议),正确解析 nexus-v1.token=。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/ws",
            subprotocols=["graphql-ws", "nexus-v1.token=test-token"],
        ) as ws:
            # 服务端只选 nexus-v1,客户端需配合(Starlette 仍协商)
            assert ws.accepted_subprotocol == "nexus-v1"
            ws.close()


def test_ws_subprotocol_malformed_value_rejected(monkeypatch) -> None:
    """subprotocol 存在但格式错误(非 nexus-v1.token=)→ 走 query 或拒绝。"""
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
