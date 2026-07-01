"""LIKE 通配符转义测试。

WHY: ``find_latest_session_by_user`` 把 user_id 嵌入 ``LIKE '%...%'`` 模式,
若 user_id 含 ``%`` 或 ``_`` 会匹配到非预期 session(P0 信息泄露)。本文件验证
``_escape_like`` 正确转义并保持原有 user_id 的字面匹配语义。
"""

from __future__ import annotations

from nexus.backend import db
from nexus.backend.db import _escape_like, find_latest_session_by_user


def test_escape_like_handles_percent() -> None:
    """% 是 LIKE 通配符,必须转义。"""
    assert _escape_like("100%") == "100\\%"


def test_escape_like_handles_underscore() -> None:
    """_ 匹配单字符,必须转义。"""
    assert _escape_like("user_1") == "user\\_1"


def test_escape_like_handles_backslash() -> None:
    """\\ 是 ESCAPE 字符,必须先于 % 和 _ 转义自身。"""
    assert _escape_like("a\\b") == "a\\\\b"


def test_escape_like_preserves_plain_text() -> None:
    """不含特殊字符的字符串应保持不变。"""
    assert _escape_like("normalid123") == "normalid123"


def test_escape_like_handles_all_combined() -> None:
    """混合转义:反斜杠先,再 %, _。"""
    assert _escape_like("a\\%b_c") == "a\\\\\\%b\\_c"


def test_find_latest_session_does_not_match_wildcard_user_id(tmp_path, monkeypatch) -> None:
    """回归测试:user_id 含 % 时不应匹配到不含该字面 user_id 的 session。

    场景:两条 wechat 会话,A 的 user_id 字面是 ``abc%xyz``,B 的 user_id 是
    ``abczxy``。调用 ``find_latest_session_by_user("abczxy")`` 只能返回 B 的
    session,不返回 A 的(m.content 字面含 ``abc%xyz``,原始 LIKE 会误中)。
    """
    # 用临时 DB 隔离
    test_db = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(test_db))
    monkeypatch.setattr(db, "_INITED", False)

    # 准备两条 wechat session + message
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, channel, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("sess-A", "wechat", "wechat acc1 abc%xyz", "2026-01-01", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO sessions (id, channel, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("sess-B", "wechat", "wechat acc1 abczxy", "2026-01-02", "2026-01-02"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            ("msg-A", "sess-A", "user", "literal abc%xyz content", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            ("msg-B", "sess-B", "user", "literal abczxy content", "2026-01-02"),
        )

    # 查询 B 的 user_id 字面(abczxy),不应匹配 A 的 session
    result = find_latest_session_by_user("abczxy", channel="wechat")
    assert result == "sess-B", f"LIKE 通配符注入导致返回错会话: 实际 {result!r}, 期望 'sess-B'"


def test_find_latest_session_escapes_backslash_user_id(tmp_path, monkeypatch) -> None:
    """回归测试:user_id 含反斜杠时不应被误解释为 ESCAPE 字符。

    场景:user_id = ``a\\b``,另一 user_id = ``a%b``。查询 ``a\\b`` 不应匹配
    含 ``a%b`` 的 session 内容(原始 LIKE 把 ``\\`` 当 ESCAPE,会把 ``%``
    当字面 %)。
    """
    test_db = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(test_db))
    monkeypatch.setattr(db, "_INITED", False)

    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, channel, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("sess-back", "wechat", "wechat acc1 a\\b", "2026-01-01", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            ("msg-back", "sess-back", "user", "literal a\\b content", "2026-01-01"),
        )

    result = find_latest_session_by_user("a\\b", channel="wechat")
    assert result == "sess-back"
