"""Plan 5 (2026-07-12):wechat 列索引化 + ``find_latest_session_by_user`` /
``list_sessions`` 改列查询的单测。

WHY:Plan 5 把 user_id → session_id 映射从 ``messages.content LIKE`` 迁移到
正经列 ``sessions.wechat_user_id`` + ``sessions.account_id``;``list_sessions``
也用 SQL ``ROW_NUMBER() OVER`` 取代 Python ``title.split()`` 解析。本文件
验证这两条主路径在多账号 / 单账号 / 软删过滤场景下行为正确。

NOTE:这些测试用 ``monkeypatch`` 重定向 DB_PATH 到 tmp,隔离现有
``~/.nexus/nexus.db``。
"""

from __future__ import annotations

from nexus.backend import db


def _setup_db(tmp_path, monkeypatch) -> None:
    test_db = tmp_path / "test_wechat.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(db, "_INITED", False)
    monkeypatch.setattr(db, "CONFIG", {**db.CONFIG, "db_path": str(test_db)})
    # 触发建表
    db.create_session("bootstrap")


def test_find_latest_returns_most_recent_wechat_session(tmp_path, monkeypatch) -> None:
    """同一 user_id 多个 session,返回 updated_at 最新的那一条。"""
    _setup_db(tmp_path, monkeypatch)

    db.create_session(
        "wx-old",
        channel="wechat",
        account_id="acc_x",
        wechat_user_id="user_p",
        title="微信 user_p 旧会话",
    )
    db.create_session(
        "wx-new",
        channel="wechat",
        account_id="acc_x",
        wechat_user_id="user_p",
        title="微信 user_p 新会话",
    )
    # 模拟时间差:更新 wx-old 的 updated_at 到更晚
    with db.get_db() as conn:
        conn.execute("UPDATE sessions SET updated_at = '2099-01-01T00:00:00' WHERE id = 'wx-old'")

    found = db.find_latest_session_by_user(user_id="user_p", channel="wechat", account_id="acc_x")
    assert found == "wx-old", f"应返回 updated_at 最大的 'wx-old', 实际 {found}"


def test_find_latest_distinguishes_by_account(tmp_path, monkeypatch) -> None:
    """多账号场景:同一 user_id 在不同账号下,只返回指定账号的最新会话。"""
    _setup_db(tmp_path, monkeypatch)

    db.create_session(
        "acc-a",
        channel="wechat",
        account_id="acc_a",
        wechat_user_id="shared_user",
    )
    db.create_session(
        "acc-b",
        channel="wechat",
        account_id="acc_b",
        wechat_user_id="shared_user",
    )

    # 限定 account_id=acc_a 不命中 acc_b
    assert db.find_latest_session_by_user(user_id="shared_user", channel="wechat", account_id="acc_a") == "acc-a"
    assert db.find_latest_session_by_user(user_id="shared_user", channel="wechat", account_id="acc_b") == "acc-b"


def test_find_latest_excludes_soft_deleted(tmp_path, monkeypatch) -> None:
    """软删的会话不进 find 结果(``deleted_at IS NOT NULL``)。"""
    _setup_db(tmp_path, monkeypatch)

    db.create_session(
        "live",
        channel="wechat",
        account_id="acc_x",
        wechat_user_id="u",
    )
    db.create_session(
        "deleted",
        channel="wechat",
        account_id="acc_x",
        wechat_user_id="u",
    )
    db.delete_session("deleted")

    found = db.find_latest_session_by_user(user_id="u", channel="wechat", account_id="acc_x")
    assert found == "live", f"软删会话应被排除,实际 {found}"


def test_find_latest_account_none_is_wildcard(tmp_path, monkeypatch) -> None:
    """``account_id=None`` 时只看 wechat_user_id,跨账号返回最新一条。"""
    _setup_db(tmp_path, monkeypatch)

    db.create_session(
        "a1",
        channel="wechat",
        account_id="acc_a",
        wechat_user_id="u",
    )
    db.create_session(
        "a2",
        channel="wechat",
        account_id="acc_b",
        wechat_user_id="u",
    )
    with db.get_db() as conn:
        conn.execute("UPDATE sessions SET updated_at = '2099-01-01' WHERE id = 'a2'")
    # account_id=None 等价于不限账号,返回 updated_at 最大的 a2
    assert db.find_latest_session_by_user(user_id="u", channel="wechat") == "a2"


def test_list_sessions_keeps_one_per_wechat_account(tmp_path, monkeypatch) -> None:
    """微信 channel 按 ``account_id`` 分组,每组只保留最新一条。"""
    _setup_db(tmp_path, monkeypatch)

    db.create_session(
        "m1",
        channel="main",
        title="main 会话 1",
    )
    db.create_session(
        "m2",
        channel="main",
        title="main 会话 2",
    )
    db.create_session(
        "w-a-old",
        channel="wechat",
        account_id="acc_a",
        wechat_user_id="u1",
        title="微信 acc_a 旧",
    )
    db.create_session(
        "w-a-new",
        channel="wechat",
        account_id="acc_a",
        wechat_user_id="u2",
        title="微信 acc_a 新",
    )
    db.create_session(
        "w-b",
        channel="wechat",
        account_id="acc_b",
        wechat_user_id="u3",
        title="微信 acc_b 唯一",
    )
    # 让 w-a-old 拥有较大 updated_at,确认它胜过 w-a-new
    with db.get_db() as conn:
        conn.execute("UPDATE sessions SET updated_at = '2099-01-01T00:00:00' WHERE id = 'w-a-old'")

    rows = db.list_sessions()
    ids = {r["id"] for r in rows}

    # main 全保留
    assert {"m1", "m2"}.issubset(ids)
    # 微信每账号一条:w-a-old(最大 updated_at) + w-b
    assert "w-a-new" not in ids, "同账号多条微信会话应只剩最新一条"
    assert "w-a-old" in ids
    assert "w-b" in ids


def test_list_sessions_excludes_soft_deleted(tmp_path, monkeypatch) -> None:
    """软删的会话不在返回列表里。"""
    _setup_db(tmp_path, monkeypatch)

    db.create_session("alive", channel="main")
    db.create_session("doomed", channel="main")
    db.delete_session("doomed")

    rows = db.list_sessions()
    ids = {r["id"] for r in rows}
    assert "alive" in ids
    assert "doomed" not in ids
