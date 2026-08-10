"""``GET /api/skills`` REST 端点测试 — SPEC §4.4。

覆盖契约:
  - ``?project_id=xxx`` → 列该 project 的 skills(per-project 隔离)
  - 无 query → 回退 ``~/.nexus/active_project.json`` → ``"default"``
  - 失败(目录不存在)/空 skills → 返回 ``{"skills": []}``,不抛
  - symlink resolve 去重(从 list_skills 行为继承)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend.db import get_db, init_db
from nexus.backend.main import app
from nexus.backend.projects.storage import ensure_default_project


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """隔离 NEXUS_HOME + WS token,初始化 DB + 默认 project。

    TestClient 默认不跑 lifespan,所以 lifespan 内的 ensure_default_project
    不会自动执行 → 手动调一次保证 default project 落盘 + DB 行存在。
    """
    from nexus.backend import config as _config

    nexus_home = tmp_path / "NexusHome"
    nexus_home.mkdir()
    (nexus_home / "skills").mkdir()  # 默认 project 的 symlink 目标
    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-token")
    monkeypatch.setitem(_config.CONFIG, "ws_token", "test-token")

    init_db()
    ensure_default_project()
    return TestClient(app)


_HEADERS = {"Authorization": "Bearer test-token"}


def test_list_skills_default_returns_skills_via_symlink(client: TestClient, tmp_path: Path) -> None:
    """``?project_id=default`` → 通过软链读 ``~/.nexus/skills/``。"""
    nexus_home = Path(__file__)  # placeholder,真实值见 client fixture
    # 通过 env 反查 NEXUS_HOME 来构造真实路径
    nexus_home = Path(__import__("os").environ["NEXUS_HOME"])
    (nexus_home / "skills" / "code-review").mkdir()
    (nexus_home / "skills" / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: review\nentrypoint: /tmp/run.sh\n---\nbody\n",
        encoding="utf-8",
    )

    r = client.get("/api/skills?project_id=default", headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["project_id"] == "default"
    names = {s["name"] for s in data["skills"]}
    assert "code-review" in names


def test_list_skills_dedupes_symlink_endpoint(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC §5.3:同 inode 经软链访问 → 端点返回 1 条。"""
    nexus_home = Path(__import__("os").environ["NEXUS_HOME"])
    real = nexus_home / "skills" / "shared-skill"
    real.mkdir()
    (real / "SKILL.md").write_text(
        "---\nname: shared-skill\ndescription: shared\nentrypoint: /tmp/run.sh\n---\nbody\n",
        encoding="utf-8",
    )
    # default project 的 skills/ 已由 ensure_default_project 设为软链 → nexus_home/skills

    r = client.get("/api/skills?project_id=default", headers=_HEADERS)
    assert r.status_code == 200
    matching = [s for s in r.json()["skills"] if s["name"] == "shared-skill"]
    assert len(matching) == 1


def test_list_skills_no_project_id_falls_back_to_active_then_default(
    client: TestClient,
) -> None:
    """无 ``?project_id=`` → 读 active_project.json,没有就 default。"""
    # 现状:active_project.json 不存在 → 应回退 default
    r = client.get("/api/skills", headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["project_id"] == "default"
    assert isinstance(data["skills"], list)


def test_list_skills_no_project_id_reads_active_json(
    client: TestClient,
) -> None:
    """无 query → 读 active_project.json。"""
    nexus_home = Path(__import__("os").environ["NEXUS_HOME"])
    active_file = nexus_home / "active_project.json"
    active_file.write_text(json.dumps({"active_project_id": "default"}), encoding="utf-8")

    r = client.get("/api/skills", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["project_id"] == "default"


def test_list_skills_custom_project_isolation(
    client: TestClient,
) -> None:
    """custom project 的 skills 与 default 完全隔离。"""
    # 创建一个 custom project 通过 DB 直插 + 建目录(避免依赖 POST /api/projects)
    from nexus.backend.projects.storage import _projects_root

    projects_root = _projects_root()
    custom = projects_root / "my-blog"
    custom.mkdir()
    (custom / "skills" / "seo-check").mkdir(parents=True)
    (custom / "skills" / "seo-check" / "SKILL.md").write_text(
        "---\nname: seo-check\ndescription: SEO\nentrypoint: /tmp/seo.sh\n---\nbody\n",
        encoding="utf-8",
    )
    now = 1_700_000_000_000
    with get_db() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, display_name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("my-blog", "my-blog", "我的博客", str(custom), now, now),
        )

    r = client.get("/api/skills?project_id=my-blog", headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["project_id"] == "my-blog"
    names = {s["name"] for s in data["skills"]}
    assert "seo-check" in names


def test_list_skills_unknown_project_returns_empty(
    client: TestClient,
) -> None:
    """不存在的 project_id → 200 + 空 list(不抛错)。"""
    r = client.get("/api/skills?project_id=nonexistent", headers=_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["project_id"] == "nonexistent"
    assert data["skills"] == []
