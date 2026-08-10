"""``GET /api/models/default/test`` 测试连接端点回归测试。

覆盖三类路径:
  - 正常:active model 有 api_key + provider ping 通过 → 200 {"ok": true}
  - 边界:无 active model / active model 无 api_key → 400
  - 异常:provider 返回 401 → 401;超时 → 408
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from nexus.backend.main import app
from nexus.backend.routes import model_config


@pytest.fixture()
def auth_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """注入固定 ws_token 并返回 bearer header。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    return {"Authorization": "Bearer test-token"}


def test_test_default_model_success(monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]) -> None:
    """active model 有 key + ping 通过 → 200 {"ok": true}。"""
    monkeypatch.setattr(
        model_config,
        "get_active_model",
        lambda: {"name": "m", "api_key": "sk-xxx", "api_base": "https://api.example.com/v1"},
    )

    async def _fake_ping(base_url: str, api_key: str) -> None:
        return None

    monkeypatch.setattr(model_config, "_ping_provider", _fake_ping)

    with TestClient(app) as client:
        resp = client.get("/api/models/default/test", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_test_default_model_no_active(monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]) -> None:
    """无 active model → 400。"""
    monkeypatch.setattr(model_config, "get_active_model", lambda: None)

    with TestClient(app) as client:
        resp = client.get("/api/models/default/test", headers=auth_headers)
    assert resp.status_code == 400


def test_test_default_model_missing_key(monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]) -> None:
    """active model 无 api_key → 400。"""
    monkeypatch.setattr(
        model_config,
        "get_active_model",
        lambda: {"name": "m", "api_key": "", "api_base": "https://api.example.com/v1"},
    )

    with TestClient(app) as client:
        resp = client.get("/api/models/default/test", headers=auth_headers)
    assert resp.status_code == 400


def test_test_default_model_provider_401(monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]) -> None:
    """provider ping 抛 401 → 端点透传 401。"""
    monkeypatch.setattr(
        model_config,
        "get_active_model",
        lambda: {"name": "m", "api_key": "bad", "api_base": "https://api.example.com/v1"},
    )

    async def _fake_ping(base_url: str, api_key: str) -> None:
        raise HTTPException(status_code=401, detail="API Key 无效")

    monkeypatch.setattr(model_config, "_ping_provider", _fake_ping)

    with TestClient(app) as client:
        resp = client.get("/api/models/default/test", headers=auth_headers)
    assert resp.status_code == 401


def test_ping_provider_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_ping_provider`` 把 httpx 超时映射为 HTTPException 408。"""

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.TimeoutException("boom")

    monkeypatch.setattr(model_config.httpx, "AsyncClient", _FakeClient)

    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(model_config._ping_provider("https://api.example.com/v1", "sk"))
    assert exc.value.status_code == 408
