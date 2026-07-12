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
    """回归测试 (Plan 5 适配):user_id 含 % 字面应只命中 wechat_user_id 列内容相同的会话。

    Plan 5 改造前用 ``messages.content LIKE ?``(LIKE 通配符注入场景)。改造后
    ``find_latest_session_by_user`` 走 ``sessions.wechat_user_id = ?`` 列等值
    查询,SQLite 不再解析 ``%`` 为通配符 — 因此本测试改为断言等值匹配语义,
    保留 P0 安全保障不变量(user_id 字面区分)。
    """
    test_db = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(test_db))
    monkeypatch.setattr(db, "_INITED", False)

    db.create_session(
        "sess-A",
        channel="wechat",
        title="wechat acc1 abc%xyz",
        account_id="acc1",
        wechat_user_id="abc%xyz",
    )
    db.create_session(
        "sess-B",
        channel="wechat",
        title="wechat acc1 abczxy",
        account_id="acc1",
        wechat_user_id="abczxy",
    )

    # 查 wechat_user_id="abczxy" 应只命中 B;A 的字面 user_id 含 % 但不相等
    assert find_latest_session_by_user("abczxy", channel="wechat") == "sess-B"
    # 反向验证:查带 % 的 user_id 也只命中 A
    assert find_latest_session_by_user("abc%xyz", channel="wechat") == "sess-A"


def test_find_latest_session_escapes_backslash_user_id(tmp_path, monkeypatch) -> None:
    """回归测试 (Plan 5 适配):反斜杠字面 user_id 应原样匹配。

    旧 LIKE 路径下 ``\\`` 是 ESCAPE 字符会导致转义歧义。新路径走 ``=`` 列
    等值,无 ESCAPE 概念 — 因此本测试改为验证反斜杠字面存进 / 查出来不丢。
    """
    test_db = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(test_db))
    monkeypatch.setattr(db, "_INITED", False)

    db.create_session(
        "sess-back",
        channel="wechat",
        account_id="acc1",
        wechat_user_id="a\\b",
    )
    assert find_latest_session_by_user("a\\b", channel="wechat") == "sess-back"
