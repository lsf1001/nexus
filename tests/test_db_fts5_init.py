"""init_db() 后 messages_fts 虚拟表 + 3 triggers 存在 + INSERT 同步。

WHY:Sidebar 当前只按 title 搜索,L7 "我昨天那条说 BTC 的在哪里?"
没法用。Round 3 加 FTS5 给 messages.content / thinking_content 建倒排索引,
配合 3 triggers 保持同步。
"""

from __future__ import annotations

import pytest

from nexus.backend import db


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """每个 test 用 tmp_path 隔离 DB,避免污染用户 ~/.nexus/。

    conftest.py 已经有 autouse fixture 做了 CONFIG["db_path"] 改写 +
    _INITED 重置,这里额外显式声明一遍,让本文件在 conftest 缺位场景
    (比如跑单文件时显式 --no-conftest)也能独立通过。
    """
    db_path = tmp_path / "test_fts.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setitem(db.CONFIG, "database_url", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield
    db._INITED = False  # type: ignore[attr-defined]


def test_init_db_creates_messages_fts() -> None:
    """FTS5 虚拟表 + 3 triggers 必须存在。"""
    db.init_db()
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE name IN ('messages_fts', 'messages_ai', 'messages_ad', 'messages_au') "
            "ORDER BY name"
        ).fetchall()
    kinds = dict(rows)
    assert "messages_fts" in kinds
    assert kinds["messages_fts"] == "table"
    assert kinds["messages_ai"] == "trigger"
    assert kinds["messages_ad"] == "trigger"
    assert kinds["messages_au"] == "trigger"


def test_messages_fts_triggers_sync_insert() -> None:
    """INSERT messages 后 messages_fts 自动同步(ai trigger 触发)。"""
    db.init_db()
    sid = db.create_session(session_id="sess-fts", channel="test")
    db.add_message(
        message_id="msg-fts-1",
        session_id=sid["id"],
        role="user",
        content="BTC 行情怎么样",
    )
    with db.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    assert n == 1


def test_messages_fts_triggers_sync_delete() -> None:
    """DELETE messages 后 messages_fts 自动同步(ad trigger 触发,delete 命令)。"""
    db.init_db()
    sid = db.create_session(session_id="sess-del", channel="test")
    db.add_message(
        message_id="msg-del-1",
        session_id=sid["id"],
        role="user",
        content="will be deleted",
    )
    with db.get_db() as conn:
        n_before = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        conn.execute("DELETE FROM messages WHERE id = ?", ("msg-del-1",))
        n_after = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    assert n_before == 1
    assert n_after == 0


def test_messages_fts_triggers_sync_update() -> None:
    """UPDATE messages 后 messages_fts 自动同步(au trigger 触发,delete+insert)。"""
    db.init_db()
    sid = db.create_session(session_id="sess-upd", channel="test")
    db.add_message(
        message_id="msg-upd-1",
        session_id=sid["id"],
        role="user",
        content="original content",
    )
    with db.get_db() as conn:
        conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            ("updated content", "msg-upd-1"),
        )
        # FTS5 用 contentless 表 + triggers 同步后,旧 rowid 已删除,新 rowid 插入。
        # 验证新词命中:
        hits_new = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?",
            ("updated",),
        ).fetchone()[0]
        hits_old = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?",
            ("original",),
        ).fetchone()[0]
    assert hits_new == 1
    assert hits_old == 0
