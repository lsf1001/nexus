"""Plan 5 (2026-07-12):sessions 表新列(account_id / wechat_user_id / channel_meta)
与 ``create_session`` 透传的单测。

WHY:验证新列被自动添加(``_ensure_column`` 幂等迁移)+ ``create_session``
写入 / 读回都正常 + JSON 序列化 ``channel_meta`` 成功。这是 wechat 索引化
的前置条件:新 ``find_latest_session_by_user`` 依赖这两列。
"""

from __future__ import annotations

import json

from nexus.backend import db


def _seed_two_sessions() -> None:
    """插 2 条微信会话:1 条有 account_id + wechat_user_id,1 条只有 main 通道。"""
    db.create_session(
        "sess-wx-1",
        title="微信会话 A",
        channel="wechat",
        account_id="wxid_acc_alpha",
        wechat_user_id="wxid_user_aaa",
        channel_meta={"appid": "wxapp_alpha"},
    )
    db.create_session(
        "sess-main-1",
        title="main 会话",
        channel="main",
    )


def test_create_session_writes_channel_columns(tmp_path, monkeypatch) -> None:
    """新 create_session 把 4 个新参(column 含 channel_meta JSON)写进 sessions 行。"""
    # 重定向 db path 到 tmp,避免污染 ~/.nexus/nexus.db
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(db, "_INITED", False)
    monkeypatch.setattr(db, "CONFIG", {**db.CONFIG, "db_path": str(test_db)})

    _seed_two_sessions()

    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-wx-1",)).fetchone()
        assert row["account_id"] == "wxid_acc_alpha"
        assert row["wechat_user_id"] == "wxid_user_aaa"
        assert row["channel"] == "wechat"
        # channel_meta 是 JSON TEXT,反序列化拿到原始 dict
        assert json.loads(row["channel_meta"]) == {"appid": "wxapp_alpha"}

        row2 = conn.execute("SELECT * FROM sessions WHERE id = ?", ("sess-main-1",)).fetchone()
        assert row2["account_id"] is None
        assert row2["wechat_user_id"] is None
        assert row2["channel_meta"] is None
        assert row2["channel"] == "main"


def test_create_session_idempotent_preserves_existing(tmp_path, monkeypatch) -> None:
    """同一 id 二次 create 不写新参,保留原列值。"""
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(db, "_INITED", False)
    monkeypatch.setattr(db, "CONFIG", {**db.CONFIG, "db_path": str(test_db)})

    db.create_session(
        "dup",
        title="原值",
        channel="wechat",
        account_id="wxid_original",
        wechat_user_id="wxid_user_orig",
        channel_meta={"k": "v"},
    )
    # 二次创建带不同值,INSERT OR IGNORE 应保留原值
    db.create_session(
        "dup",
        title="应被忽略",
        channel="main",
        account_id="ignored",
        wechat_user_id="ignored_user",
        channel_meta={"ignored": True},
    )
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", ("dup",)).fetchone()
        assert row["account_id"] == "wxid_original"
        assert row["wechat_user_id"] == "wxid_user_orig"
        assert json.loads(row["channel_meta"]) == {"k": "v"}
        assert row["channel"] == "wechat"


def test_ensure_column_idempotent(tmp_path, monkeypatch) -> None:
    """重跑 _create_tables 不抛错(``IF NOT EXISTS`` + ``_ensure_column`` PRAGMA 探测)。"""
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setattr(db, "_INITED", False)
    monkeypatch.setattr(db, "CONFIG", {**db.CONFIG, "db_path": str(test_db)})

    db.create_session("first", channel="wechat", wechat_user_id="u1")
    # 强制重置 _INITED,模拟进程重启
    db._INITED = False
    # 再次创建不抛错 → DB schema 幂等
    db.create_session("second", channel="main")
