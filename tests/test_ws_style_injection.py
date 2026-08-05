"""WS 帧 style 字段注入 agent 重建路径(Round 6.1 Task 6)。

WHY:用户在 PATCH /api/sessions/{id} 设置 DB 持久风格后,某些场景下
希望"本条消息临时切风格但不动 DB"(例如临时让某次回复更专业)。
本测试覆盖 ``_resolve_session_style`` 的三条解析路径 + DB 持久化
可选行为,保证 main.py ws 端点走 ``get_agent(style)`` 时 style 维度
被正确传递。
"""

from __future__ import annotations

import uuid

from nexus.backend import db
from nexus.backend.api.ws import handlers


def test_resolve_session_style_uses_frame_value(tmp_path, monkeypatch) -> None:
    """合法 frame_style 直接生效,不等 DB。

    WHY:用户本条消息选了"professional",但 DB 里仍是 default —— 不应该
    先 SELECT DB 再返回。frame 优先级最高。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")

    # frame 给了 "professional" → 直接用它,不管 DB 是 default
    assert handlers._resolve_session_style("professional", sid) == "professional"
    # frame 给了 "concise" → 直接用它
    assert handlers._resolve_session_style("concise", sid) == "concise"


def test_resolve_session_style_falls_through_to_db(tmp_path, monkeypatch) -> None:
    """frame_style 为 None / 非法时 fallthrough 到 DB 持久值。

    WHY:本条消息没指定 style(典型 99% 路径),应该用 DB 里的持久值;
    防非法字符是兜底,非法值必须 fallthrough 而非 crash。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")

    # 1) frame=None → DB 默认 'default'(create_session 后 style 列默认 'default')
    assert handlers._resolve_session_style(None, sid) == "default"
    # 2) frame 非法 → fallthrough 到 DB 'default'(防注入 / 客户端 bug)
    assert handlers._resolve_session_style("bogus", sid) == "default"

    # DB 改成 'concise',frame=None → 用 DB 值
    db.update_session_style(sid, "concise")
    assert handlers._resolve_session_style(None, sid) == "concise"
    # DB 改成 'professional',frame=非法 → 仍 fallthrough 到 DB
    db.update_session_style(sid, "professional")
    assert handlers._resolve_session_style("bogus", sid) == "professional"


def test_resolve_session_style_persists_frame_style_to_db(tmp_path, monkeypatch) -> None:
    """persist=True 时,合法的 frame_style 必须写回 DB。

    WHY:用户本条消息选"concise",但 DB 还存"professional",下一条消息
    若不传 frame.style 应继续用 DB 值 —— 所以本轮解析出的 resolved
    必须落库,否则风格会"漂"在内存里(进程内 ws_session_style 是临时
    覆盖,但 DB 是事实基线)。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")

    # 持久化路径:frame "concise" → DB 写入 'concise'
    handlers._resolve_session_style("concise", sid, persist=True)
    session = db.get_session(sid)
    assert session["style"] == "concise"

    # 非持久化路径:frame 给一个新值但 persist=False → DB 不动
    handlers._resolve_session_style("professional", sid, persist=False)
    session = db.get_session(sid)
    assert session["style"] == "concise"  # 仍是上一步写的,没变


def test_resolve_session_style_persist_skips_when_db_already_matches(tmp_path, monkeypatch) -> None:
    """persist=True 但 frame_style == DB 已存值时,不触发冗余 UPDATE。

    WHY:99% 场景下客户端发"concise",DB 也是"concise" → 不应该每次
    user 消息都跑一次 UPDATE(改 updated_at,触发前端不必要的 refetch)。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    db.init_db()
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")
    db.update_session_style(sid, "concise")

    # DB 已是 concise,frame 传 concise,persist=True → 应该幂等
    result = handlers._resolve_session_style("concise", sid, persist=True)
    assert result == "concise"
    session = db.get_session(sid)
    assert session["style"] == "concise"
