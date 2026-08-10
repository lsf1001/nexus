"""Regression: conftest autouse 必须调 ensure_default_project()。

WHY: 历史上 conftest 只 init_db() 建表不建默认 row,导致 28 个 db 测试
FK 失败。这文件是回归测试 —— 它不依赖任何额外 fixture,只依赖 autouse,
如果有人误删 conftest 那行,这文件会立刻 RED。
"""

from nexus.backend import db


def test_autouse_creates_default_project() -> None:
    """autouse 跑完后,projects 表至少 1 行。"""
    with db.get_db() as conn:
        rows = conn.execute("SELECT id FROM projects").fetchall()
    assert any(r["id"] == "default" for r in rows), f"expected default project row, got {[r['id'] for r in rows]}"


def test_autouse_create_session_does_not_violate_fk() -> None:
    """autouse 后 create_session() 不再 FK 失败。

    WHY:create_session 第一参数必填 session_id(客户端 WS 首条消息传的),
    其它字段有默认。我们只验证 autouse 让 FK 约束不抛,不动其它字段语义。
    """
    row = db.create_session(session_id="autouse-fk-smoke", channel="test")
    assert row["id"] == "autouse-fk-smoke"
