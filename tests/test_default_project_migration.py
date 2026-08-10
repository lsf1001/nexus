"""默认 Project 启动期迁移 — SPEC §4.2。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend import db
from nexus.backend.db import get_db, init_db
from nexus.backend.projects.storage import (
    ensure_default_project,
    migrate_sessions_to_default,
)


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    # DB 也指向 tmp_path,避免污染真实 ~/.nexus/nexus.db
    monkeypatch.setitem(db.CONFIG, "db_path", str(tmp_path / "nexus.db"))
    monkeypatch.setattr(db, "_INITED", False)
    # 创建空的 ~/.nexus/skills/ + AGENTS.md,模拟已有用户
    (tmp_path / "skills").mkdir()
    (tmp_path / "AGENTS.md").write_text("# User memory\ntest content\n")
    # default_project_path() 走 _get_nexus_home().parent / "Nexus" / "projects",
    # 即 tmp_path.parent / "Nexus" / "projects" — 与 tmp_path 同生命周期,无需清盘。
    yield tmp_path


def test_ensure_default_project_creates_row_and_dirs(nexus_home: Path) -> None:
    init_db()
    ensure_default_project()
    with get_db() as conn:
        row = conn.execute("SELECT id, name, display_name, path FROM projects WHERE id='default'").fetchone()
    assert row is not None
    assert dict(row)["name"] == "default"
    project_path = Path(dict(row)["path"])
    assert project_path.is_dir(), "默认 Project 目录必须被创建"
    assert (project_path / "AGENTS.md").exists(), "AGENTS.md 必须从 ~/.nexus 拷贝"
    assert (project_path / "AGENTS.md").read_text().startswith("# User memory")
    # skills/ 是软链 → ~/.nexus/skills/
    skills_link = project_path / "skills"
    assert skills_link.is_symlink(), "skills/ 必须是软链"
    assert skills_link.resolve() == (nexus_home / "skills").resolve()


def test_ensure_default_project_idempotent(nexus_home: Path) -> None:
    """重跑迁移不破坏已有目录 / 不报错。"""
    init_db()
    ensure_default_project()
    first_path = None
    with get_db() as conn:
        first_path = conn.execute("SELECT path FROM projects WHERE id='default'").fetchone()["path"]
    ensure_default_project()  # 第二次
    with get_db() as conn:
        second_path = conn.execute("SELECT path FROM projects WHERE id='default'").fetchone()["path"]
    assert first_path == second_path, "重跑迁移不能改 path"
    # 不应该新建第二份 AGENTS.md
    default_dir = Path(first_path)
    agents = list(default_dir.glob("AGENTS.md"))
    assert len(agents) == 1, "AGENTS.md 必须只有一份"


def test_migrate_sessions_to_default_sets_null_to_default(nexus_home: Path) -> None:
    """现有 sessions.project_id 为 NULL 时,迁移到 'default'。"""
    init_db()
    ensure_default_project()
    # 插入一条 sessions 行,project_id 留 NULL(模拟旧库)
    now = 1_700_000_000_000
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, channel, project_id) "
            "VALUES (?, ?, ?, ?, 'main', NULL)",
            ("s1", "test", str(now), str(now)),
        )
    migrate_sessions_to_default()
    with get_db() as conn:
        pid = conn.execute("SELECT project_id FROM sessions WHERE id='s1'").fetchone()["project_id"]
    assert pid == "default", "旧 session 必须迁到 default"


def test_migrate_sessions_does_not_overwrite_existing(nexus_home: Path) -> None:
    """已带 project_id 的 sessions 不被迁移覆盖。"""
    init_db()
    ensure_default_project()
    now = 1_700_000_000_000
    with get_db() as conn:
        # 插入另一个 project + 一条已归属它的 session
        conn.execute(
            "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES ('p1', 'other', '/tmp/other', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, channel, project_id) "
            "VALUES ('s2', 'test', ?, ?, 'main', 'p1')",
            (str(now), str(now)),
        )
    migrate_sessions_to_default()
    with get_db() as conn:
        pid = conn.execute("SELECT project_id FROM sessions WHERE id='s2'").fetchone()["project_id"]
    assert pid == "p1", "已归属的 session 不能被覆写"


def test_ensure_default_project_does_not_overwrite_user_edited_agents(
    nexus_home: Path,
) -> None:
    """用户编辑默认 Project 的 AGENTS.md 后重启,内容必须保留(C1 修复)。

    WHY:旧实现无条件 shutil.copy2 会擦掉用户编辑,且重启期反复触发;
    现已在 _copy_agents_md 顶部加 if dst.exists(): return 守卫。
    """
    init_db()
    ensure_default_project()
    # 模拟用户编辑
    with get_db() as conn:
        path = conn.execute("SELECT path FROM projects WHERE id='default'").fetchone()["path"]
    agents = Path(path) / "AGENTS.md"
    agents.write_text("# 用户定制内容\n", encoding="utf-8")
    # 重跑迁移
    ensure_default_project()
    # 内容必须保留
    assert agents.read_text(encoding="utf-8") == "# 用户定制内容\n", "用户编辑的 AGENTS.md 不应被覆盖"
