"""DB 迁移测试：quality_scores / resume_tokens 表。

验证 Phase 1 容错新增的 2 张表:
  - 干净库启动后表存在
  - 老库（只有旧 5 张表）启动后自动创建新表，老数据不丢
  - 表字段完整
  - 迁移幂等（IF NOT EXISTS 不会报错）
"""

from __future__ import annotations

import sqlite3

import pytest

from nexus.backend import db
from nexus.backend.db import _create_tables


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """每个测试用独立临时 DB 文件。"""
    db_path = tmp_path / "test.db"
    # 改 CONFIG 里的 db_path
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    # 重置 _INITED 否则后续测试不会跑 _create_tables
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    # 清理
    monkeypatch.setattr(db, "_INITED", False)


def test_fresh_db_creates_all_tables(temp_db):
    """干净库启动后所有表（包括新表）都存在。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    conn.commit()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    table_names = {r[0] for r in rows}
    expected = {
        "sessions",
        "messages",
        "memory",
        "tool_stats",
        "session_stats",
        "quality_scores",
        "resume_tokens",
    }
    assert expected.issubset(table_names), f"missing: {expected - table_names}"


def test_quality_scores_table_schema(temp_db):
    """quality_scores 表字段完整。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(quality_scores)").fetchall()}
    assert {"id", "session_id", "message_id", "rubric", "score", "verdict", "reasoning", "created_at"} <= cols


def test_resume_tokens_table_schema(temp_db):
    """resume_tokens 表字段完整。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(resume_tokens)").fetchall()}
    assert {"token", "session_id", "last_event_id", "expires_at", "created_at"} <= cols


def test_old_db_auto_migrates_without_data_loss(temp_db):
    """老库（只有旧 5 张表）启动后，新表自动创建；老表的数据不丢。"""
    conn = sqlite3.connect(str(temp_db))
    # 1. 先按老 schema 建表 + 插一条数据（schema 跟当前一致，只是没有新 2 张表）
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            channel TEXT DEFAULT 'main'
        );
        INSERT INTO sessions VALUES ('sess-old', '老会话', '2024-01-01', '2024-01-01', NULL, 'main');
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            thinking_content TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO messages VALUES ('msg-1', 'sess-old', 'user', '历史消息', NULL, '2024-01-01');
    """)
    conn.commit()

    # 2. 跑 _create_tables（模拟启动）
    _create_tables(conn)
    conn.commit()

    # 3. 验证老数据还在
    sess = conn.execute("SELECT id, title FROM sessions WHERE id='sess-old'").fetchone()
    assert sess[0] == "sess-old"
    assert sess[1] == "老会话"

    msg = conn.execute("SELECT content FROM messages WHERE id='msg-1'").fetchone()
    assert msg[0] == "历史消息"

    # 4. 验证新表已存在且可写
    conn.execute(
        "INSERT INTO quality_scores (session_id, rubric, score, verdict) VALUES (?, ?, ?, ?)",
        ("sess-old", "faithfulness", 0.9, "accept"),
    )
    conn.execute(
        "INSERT INTO resume_tokens (token, session_id, last_event_id, expires_at) VALUES (?, ?, ?, ?)",
        ("tok-1", "sess-old", 42, "2026-12-31 23:59:59"),
    )
    conn.commit()

    # 5. 读回
    qs = conn.execute("SELECT score FROM quality_scores WHERE session_id='sess-old'").fetchone()
    assert qs[0] == 0.9
    rt = conn.execute("SELECT last_event_id FROM resume_tokens WHERE token='tok-1'").fetchone()
    assert rt[0] == 42


def test_migration_is_idempotent(temp_db):
    """重复调用 _create_tables 不会报错（IF NOT EXISTS 保证）。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)  # 第 1 次
    _create_tables(conn)  # 第 2 次
    _create_tables(conn)  # 第 3 次
    conn.commit()
    # 全部表都还在
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert any(r[0] == "quality_scores" for r in rows)
    assert any(r[0] == "resume_tokens" for r in rows)
