"""projects 表 schema + sessions.project_id 列迁移测试。

Round 1 SPEC §4.1:Project 骨架第一步,只验 DB schema,不动业务代码。

覆盖:
  1. ``projects`` 表在 ``init_db()`` 后存在
  2. ``sessions.project_id`` 列在 ``init_db()`` 后存在(自动迁移)
  3. ``projects.name`` UNIQUE 约束生效(插入重复 name 触发 IntegrityError)
"""

from __future__ import annotations

import sqlite3

import pytest

from nexus.backend import db


@pytest.fixture
def fresh_db(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试拿到独立的临时 DB 路径,避免污染真实 ~/.nexus/nexus.db。

    直接 ``monkeypatch.setitem(db.CONFIG, ...)`` 改 dict 项,不依赖
    ``NEXUS_HOME`` env(``CONFIG`` 是模块加载期单例,setenv 不会重新解析)。
    同时重置 ``_INITED`` 让 ``init_db()`` 真跑迁移。
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)


def test_projects_table_created_on_init_db(fresh_db: None) -> None:
    """``projects`` 表必须由 ``_create_tables`` 创建。"""
    db.init_db()
    with db.get_db() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projects'").fetchall()
    assert len(rows) == 1, "projects 表必须被 _create_tables 创建"


def test_sessions_project_id_column_exists(fresh_db: None) -> None:
    """``sessions`` 表必须有 ``project_id`` 列(旧库走 _ensure_column 自动 ALTER)。"""
    db.init_db()
    with db.get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "project_id" in cols, "sessions 表必须有 project_id 列"


def test_projects_name_unique_constraint(fresh_db: None) -> None:
    """``projects.name`` UNIQUE 约束:name 不允许重复(重复插入触发 IntegrityError)。"""
    db.init_db()
    now = 1_700_000_000_000
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, display_name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("p1", "alpha", "Alpha", "/tmp/alpha", now, now),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO projects (id, name, display_name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("p2", "alpha", "Alpha Dup", "/tmp/alpha2", now, now),
            )
