"""测试模型配置 REST API（routes/model_config.py）。"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.backend.routes import model_config as mc_routes
from nexus.backend.routes.model_config import router


@pytest.fixture
def app_with_tmp_config(tmp_path: Path):
    """挂载路由到临时 FastAPI 应用，并指向临时配置文件。"""
    from nexus.backend import models_config

    test_file = tmp_path / "models.json"
    initial = {
        "models": [
            {
                "id": "m1",
                "name": "Model 1",
                "api_key": "key-1",
                "api_base": "https://api.example.com",
                "temperature": 0.7,
                "is_active": True,
            }
        ]
    }
    test_file.write_text(__import__("json").dumps(initial), encoding="utf-8")

    # 注入空依赖（这些路由不实际触发 agent 切换）
    mc_routes.init_router(
        agent_lock=__import__("threading").Lock(),
        mcp_tools=[],
        create_agent_with_model=lambda *a, **kw: None,
        set_global_agent=lambda *a, **kw: None,
    )

    app = FastAPI()
    app.include_router(router)

    with patch.object(models_config, "MODELS_FILE", test_file):
        yield app, test_file


@pytest.fixture
def client(app_with_tmp_config) -> TestClient:
    app, _ = app_with_tmp_config
    return TestClient(app)


class TestGetModels:
    """GET /api/models"""

    def test_returns_list(self, client: TestClient) -> None:
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "m1"


class TestCreateModel:
    """POST /api/models"""

    def test_create_success(self, client: TestClient, app_with_tmp_config) -> None:
        app, test_file = app_with_tmp_config
        resp = client.post(
            "/api/models",
            json={
                "id": "m2",
                "name": "Model 2",
                "api_key": "key-2",
                "api_base": "https://api2.example.com",
                "temperature": 0.5,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["model"]["id"] == "m2"
        # 验证已写入文件
        import json
        cfg = json.loads(test_file.read_text(encoding="utf-8"))
        ids = {m["id"] for m in cfg["models"]}
        assert ids == {"m1", "m2"}

    def test_create_duplicate_id_returns_409(self, client: TestClient) -> None:
        resp = client.post(
            "/api/models",
            json={"id": "m1", "name": "Dup"},
        )
        assert resp.status_code == 409
        assert "已存在" in resp.json()["detail"]


class TestUpdateModel:
    """PUT /api/models/{id}"""

    def test_update_name(self, client: TestClient) -> None:
        resp = client.put(
            "/api/models/m1",
            json={"name": "Renamed Model"},
        )
        assert resp.status_code == 200
        assert resp.json()["model"]["name"] == "Renamed Model"

    def test_update_missing_returns_404(self, client: TestClient) -> None:
        resp = client.put(
            "/api/models/nonexistent",
            json={"name": "X"},
        )
        assert resp.status_code == 404


class TestDeleteModel:
    """DELETE /api/models/{id}"""

    def test_delete_min_guard(self, client: TestClient) -> None:
        """只剩一个模型时不能删除。"""
        resp = client.delete("/api/models/m1")
        assert resp.status_code == 400
        assert "至少需要保留" in resp.json()["detail"]

    def test_delete_missing_returns_404(self, client: TestClient) -> None:
        # 先创建一个额外的，然后删除一个不存在的
        client.post("/api/models", json={"id": "m2", "name": "M2"})
        resp = client.delete("/api/models/nonexistent")
        assert resp.status_code == 404

    def test_delete_success(self, client: TestClient) -> None:
        # 准备两个模型
        client.post("/api/models", json={"id": "m2", "name": "M2"})
        resp = client.delete("/api/models/m2")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
