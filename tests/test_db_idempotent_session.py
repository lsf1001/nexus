"""create_session idempotent 回归测试(防 #42 回归)。

Bug:客户端在 WS 首条消息 body 传 ``session_id``,但服务端 ``create_session``
早期实现用裸 ``INSERT``,不查存在性,导致后续 ``add_message`` 触发
FOREIGN KEY constraint failed(因 session_id 不在 sessions 表里)。

修复:create_session 改用 ``INSERT OR IGNORE`` + ``SELECT`` 取回真实行。
本测试验证:
  - 同一 id 调 create_session 两次,第二次不抛 IntegrityError
  - 第二次调用不会覆盖已存在的 title / channel(已存行保留)
  - 调 create_session 后立即 add_message 不再 FK 失败
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nexus.backend import db
from nexus.backend.db import add_message, create_session, get_session


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """每个测试用独立临时 DB 文件。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


def test_create_session_idempotent_no_error(temp_db: Path) -> None:
    """同一 session_id 调两次不抛异常(原 bug 会抛 IntegrityError)。"""
    create_session("sess-x", title="first", channel="main")
    # 第二次调用不应抛异常
    result = create_session("sess-x", title="second-attempt", channel="wechat")
    assert result["id"] == "sess-x"


def test_create_session_idempotent_preserves_existing(temp_db: Path) -> None:
    """已存在的 session 行 title / channel 不会被覆盖(保留原值)。"""
    create_session("sess-y", title="original-title", channel="wechat")
    result = create_session("sess-y", title="new-title", channel="main")
    # 第一次写入的 channel='wechat' 保留
    assert result["channel"] == "wechat"
    assert result["title"] == "original-title"


def test_create_session_then_add_message_no_fk(temp_db: Path) -> None:
    """回归 #42:create_session + add_message 在同 session_id 下不触发 FK 失败。"""
    sid = "sess-z"
    create_session(sid, title="z", channel="main")
    # 关键:这条 add_message 在原 bug 下会 FOREIGN KEY constraint failed
    msg = add_message("msg-1", sid, "user", "hello")
    assert msg["session_id"] == sid

    # 验证 messages 行真在表里
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute("SELECT session_id FROM messages WHERE id = ?", ("msg-1",)).fetchone()
        assert row is not None
        assert row[0] == sid
    finally:
        conn.close()


def test_get_session_returns_existing_row(temp_db: Path) -> None:
    """get_session 在 create_session 之后能拿到完整行。"""
    create_session("sess-w", title="w-title", channel="main")
    row = get_session("sess-w")
    assert row is not None
    assert row["title"] == "w-title"
    assert row["channel"] == "main"


def test_get_session_returns_none_for_missing(temp_db: Path) -> None:
    """get_session 对不存在的 id 返回 None — 给 WS handler 的存在性判断用。"""
    assert get_session("does-not-exist") is None
