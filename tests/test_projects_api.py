"""Project REST API 测试 — SPEC §4.3。

Round 1 骨架第三步:REST CRUD + 文件系统初始化。
覆盖端点:
  - GET    /api/projects
  - GET    /api/projects/{id}
  - POST   /api/projects            (slug 校验 + 重复 name → 409 + 目录初始化)

WHY 不在测试里 mock storage:直接走 FastAPI TestClient 验证端到端,
包括路由注册 / 鉴权 / DB / 文件系统。这是 acceptance test,而不是单测。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend import db as _db
from nexus.backend.config import CONFIG as _CONFIG
from nexus.backend.db import init_db
from nexus.backend.main import app
from nexus.backend.projects.storage import ensure_default_project


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """隔离 NEXUS_HOME + db 路径 + ws_token,跑一次 init_db + ensure_default_project。

    WHY 同时 monkeypatch CONFIG:CONFIG 是模块加载期单例,setenv 改不到
    ``db_path`` / ``ws_token``;storage._get_nexus_home() 走 call-time env
    读取,setenv 有效。三边各打各的,确保 storage + db + auth 全隔离。
    """
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-token")
    monkeypatch.setitem(_CONFIG, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setitem(_CONFIG, "ws_token", "test-token")
    monkeypatch.setattr(_db, "_INITED", False)
    init_db()
    ensure_default_project()
    # TestClient 默认不触发 lifespan;init_db + ensure_default_project 已手动跑过,
    # 不需要再让 lifespan 跑一遍。
    yield TestClient(app)


_HEADERS = {"Authorization": "Bearer test-token"}


def test_list_projects_returns_default(client: TestClient) -> None:
    """GET /api/projects 至少返回 default project。"""
    r = client.get("/api/projects", headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(p["id"] == "default" for p in data)


def test_create_project_with_valid_name(client: TestClient) -> None:
    """POST /api/projects → 201,目录 + AGENTS.md + skills + mcp.json 全建好。"""
    r = client.post(
        "/api/projects",
        headers={**_HEADERS, "Content-Type": "application/json"},
        json={"name": "my-blog", "display_name": "我的博客", "description": "写作项目"},
    )
    assert r.status_code == 201, r.text
    proj = r.json()
    assert proj["name"] == "my-blog"
    assert proj["display_name"] == "我的博客"

    project_path = Path(proj["path"])
    assert project_path.is_dir(), f"目录未创建: {project_path}"
    assert (project_path / "AGENTS.md").exists(), "AGENTS.md 必须存在"
    skills = project_path / "skills"
    assert skills.is_dir() or skills.is_symlink(), "skills 目录必须存在"
    assert (project_path / "mcp.json").exists(), "mcp.json 必须存在"


def test_create_project_rejects_invalid_slug(client: TestClient) -> None:
    """name 含空格/大写/标点 → 422(Pydantic) 或 400(自定义校验)。

    Pydantic Field 走 422 路径更标准;plan 写 400 走自定义,但 slug 在
    Pydantic pattern 内已拦截。我们同时接受 400/422 以兼容两种实现。
    """
    r = client.post(
        "/api/projects",
        headers={**_HEADERS, "Content-Type": "application/json"},
        json={"name": "My Project!", "display_name": "x"},
    )
    assert r.status_code in (400, 422), f"期望 400/422,实际 {r.status_code}"


def test_create_project_rejects_duplicate_name(client: TestClient) -> None:
    """重复 name → 409。"""
    r1 = client.post(
        "/api/projects",
        headers={**_HEADERS, "Content-Type": "application/json"},
        json={"name": "alpha", "display_name": "Alpha"},
    )
    assert r1.status_code == 201, r1.text

    r2 = client.post(
        "/api/projects",
        headers={**_HEADERS, "Content-Type": "application/json"},
        json={"name": "alpha", "display_name": "Alpha Dup"},
    )
    assert r2.status_code == 409, f"重复 name 期望 409,实际 {r2.status_code}"


def test_get_project_by_id(client: TestClient) -> None:
    """GET /api/projects/{id} → 200 + 字段正确。"""
    r = client.get("/api/projects/default", headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "default"
    assert data["name"] == "default"
    assert "path" in data
    assert "created_at" in data
