"""DB schema migration: sessions.style 列 + update_session_style 函数。"""

import uuid

import pytest

from nexus.backend import db


def test_sessions_table_has_style_column() -> None:
    """init_db() 后 sessions 表必须有 style 列（自迁移）。"""
    db.init_db()
    with db.get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "style" in cols


def test_update_session_style_validates_enum(tmp_path, monkeypatch) -> None:
    """拒绝不在合法枚举内的会话风格。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")

    with pytest.raises(ValueError, match="invalid style"):
        db.update_session_style(sid, "bogus_style")


def test_update_session_style_validates_session_exists(tmp_path, monkeypatch) -> None:
    """拒绝更新不存在会话的风格。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()

    with pytest.raises(ValueError, match="session 不存在"):
        db.update_session_style("nonexistent-sid", "concise")


def test_update_session_style_persists(tmp_path, monkeypatch) -> None:
    """合法会话风格必须持久化。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")

    db.update_session_style(sid, "professional")
    session = db.get_session(sid)
    assert session["style"] == "professional"


def test_get_session_default_style(tmp_path, monkeypatch) -> None:
    """新会话的默认风格必须为 default。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")
    session = db.get_session(sid)
    assert session["style"] == "default"


def test_list_sessions_includes_style(tmp_path, monkeypatch) -> None:
    """会话列表中的每条记录必须包含 style。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    db.create_session(str(uuid.uuid4()), title="A", channel="test")
    db.create_session(str(uuid.uuid4()), title="B", channel="test")
    sessions = db.list_sessions()
    assert all("style" in session for session in sessions)
