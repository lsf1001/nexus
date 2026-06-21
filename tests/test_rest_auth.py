"""REST API 鉴权回归测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from nexus.backend.main import app


def test_rest_routes_reject_missing_token(monkeypatch) -> None:
    """会话、模型和通道接口缺少 token 时应拒绝访问。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")

    with TestClient(app) as client:
        assert client.get("/api/sessions").status_code == 401
        assert client.get("/api/models").status_code == 401
        assert client.get("/api/channels").status_code == 401


def test_rest_routes_accept_bearer_token(monkeypatch) -> None:
    """受保护 REST 接口应接受与 WebSocket 共享的 bearer token。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        assert client.get("/api/sessions", headers=headers).status_code == 200
        assert client.get("/api/models", headers=headers).status_code == 200
        assert client.get("/api/channels", headers=headers).status_code == 200
