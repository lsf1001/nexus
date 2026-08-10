"""init_db() 后 share_tokens 表 + idx_share_tokens_session 索引存在。

WHY:会话分享链接需要 server-side token 映射 —
``resume_tokens`` 是 WS 续传 HMAC(短命,与 ws 帧挂钩),
不能复用。share_tokens 是显式 user 触发的"创建公开只读快照",
可以 7 天过期 + 撤销。
"""

from __future__ import annotations

import pytest

from nexus.backend import db


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """每个 test 用 tmp_path 隔离 DB。conftest 已 autouse 改写 CONFIG,
    这里额外显式声明一遍,让本文件在 conftest 缺位场景也能独立通过。"""
    db_path = tmp_path / "test_share.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setitem(db.CONFIG, "database_url", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield
    db._INITED = False  # type: ignore[attr-defined]


def test_init_db_creates_share_tokens() -> None:
    """share_tokens 表 + session_id 索引必须存在。"""
    db.init_db()
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE name IN ('share_tokens', 'idx_share_tokens_session') "
            "ORDER BY name"
        ).fetchall()
    kinds = dict(rows)
    assert "share_tokens" in kinds
    assert kinds["share_tokens"] == "table"
    assert "idx_share_tokens_session" in kinds
    assert kinds["idx_share_tokens_session"] == "index"


def test_share_tokens_references_session_fk() -> None:
    """share_tokens.session_id 必须有外键 → sessions.id。"""
    db.init_db()
    sid = db.create_session(session_id="sess-share", channel="test")
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO share_tokens (token, session_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                "tok-share-001",
                sid["id"],
                "2026-08-05T00:00:00",
                "2026-08-12T00:00:00",
            ),
        )
        row = conn.execute(
            "SELECT session_id, revoked_at FROM share_tokens WHERE token = ?",
            ("tok-share-001",),
        ).fetchone()
    assert row["session_id"] == sid["id"]
    assert row["revoked_at"] is None  # 默认未撤销
