"""DB 迁移测试：messages 表新增 intent 列（意图识别路由）。

验证:
  - _create_tables 后 messages 表存在 intent 列
  - add_message 接受 intent 参数并写入
  - add_message 不传 intent 时字段为 NULL（向后兼容）
"""

from __future__ import annotations

import sqlite3

import pytest

from nexus.backend import db
from nexus.backend.db import _create_tables, add_message


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """每个测试用独立临时 DB 文件。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


def _seed_session(db_path) -> None:
    """预创建 session,满足 add_message 的 FOREIGN KEY + sessions UPDATE 依赖。"""
    conn = sqlite3.connect(str(db_path))
    now = "2026-01-01T00:00:00"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, channel) VALUES (?, ?, ?, ?, ?)",
        ("s1", None, now, now, "main"),
    )
    conn.execute(
        "INSERT INTO session_stats (session_id, created_at) VALUES (?, ?)",
        ("s1", now),
    )
    conn.commit()
    conn.close()


def test_messages_table_has_intent_column(temp_db):
    """_create_tables 后 messages 表必须有 intent 列。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert "intent" in cols


def test_add_message_persists_intent(temp_db):
    """add_message 接受 intent 参数并写入。"""
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    _seed_session(temp_db)
    add_message("m1", "s1", "user", "你好", intent="chitchat")
    row = conn.execute("SELECT intent FROM messages WHERE id = 'm1'").fetchone()
    assert row["intent"] == "chitchat"


def test_add_message_default_intent_is_none(temp_db):
    """不传 intent 时,字段为 NULL(老路径行为不变)。"""
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    _seed_session(temp_db)
    add_message("m2", "s1", "user", "test")
    row = conn.execute("SELECT intent FROM messages WHERE id = 'm2'").fetchone()
    assert row["intent"] is None
