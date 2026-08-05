"""FTS5 全文搜索:跨会话搜 user + assistant 消息正文 + snippet 高亮。

Round 3 Task 3.2:在 Task 3.1 把 messages_fts 虚拟表 + 3 triggers 建好之后,
业务层(db.search_messages + /api/search/messages)接通,验证:
- 命中 user + assistant 双角色
- snippet 用 <mark>...</mark> 高亮
- bm25 排序(命中越多次排名越前)
- thinking_content 字段也能命中
- 空查询 / 无匹配 返回 []
- FTS5 syntax 错走 HTTPException 400(走 ROUTER 层,不在此文件的覆盖)

WHY message_id 返回:测试「test_search_finds_thinking_content」要
确认 msg_id 与原 add_message 返回的 id 一致,前端消息级锚点会用到。

worker 备注:本测试跑前 Task 3.1 已把 messages_fts + 3 triggers 建出来,
init_db() 正常路径下 schema 完整,无需手动 create。
"""

from __future__ import annotations

import pytest

from nexus.backend import db


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """每个 test 用 tmp_path 隔离 DB。

    conftest 已有 autouse 做 _INITED 重置 + CONFIG["db_path"] 改写。
    这里显式再标一次,让本文件独立跑 --no-conftest 也能过(防御性)。
    """
    db_path = tmp_path / "test_search.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setitem(db.CONFIG, "database_url", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield
    monkeypatch.setattr(db, "_INITED", False)


def test_search_returns_matching_messages() -> None:
    """搜索词命中 user + assistant 两条消息,跨会话过滤。"""
    db.init_db()
    sid1 = db.create_session(session_id="sess-1", channel="test")
    sid2 = db.create_session(session_id="sess-2", channel="test")
    db.add_message("msg-u1", sid1["id"], "user", "元力股份还能买吗")
    db.add_message("msg-a1", sid1["id"], "assistant", "看技术面和资金面")
    db.add_message("msg-u2", sid2["id"], "user", "BTC 接下来怎么走")
    db.add_message("msg-a2", sid2["id"], "assistant", "看美联储利率决议")

    results = db.search_messages("元力股份")
    assert len(results) == 1
    assert results[0]["session_id"] == sid1["id"]
    assert results[0]["content"] == "元力股份还能买吗"
    assert results[0]["role"] == "user"
    assert "<mark>" in results[0]["snippet"]
    assert "</mark>" in results[0]["snippet"]


def test_search_ranks_better_match_higher() -> None:
    """bm25 排序:命中 3 次的高于命中 1 次的。"""
    db.init_db()
    row = db.create_session(session_id="sess-btc", channel="test")
    sid = row["id"]
    db.add_message("msg-btc-1", sid, "user", "BTC 行情")
    db.add_message("msg-btc-2", sid, "assistant", "BTC BTC BTC 持续走高")  # 命中 3 次

    results = db.search_messages("BTC")
    assert len(results) == 2
    # 命中 3 次的排前
    assert results[0]["content"].count("BTC") == 3
    assert results[1]["content"].count("BTC") == 1


def test_search_empty_query_returns_empty() -> None:
    """空查询 / 纯空白 → []。调用方(FastAPI)已用 min_length=1 拦一次,
    这里覆边界:走 search_messages 直调也得安全。"""
    db.init_db()
    row = db.create_session(session_id="sess-empty", channel="test")
    sid = row["id"]
    db.add_message("msg-empty", sid, "user", "BTC 行情")
    assert db.search_messages("") == []
    assert db.search_messages("   ") == []
    assert db.search_messages("\t\n") == []


def test_search_no_match_returns_empty() -> None:
    """查询词不存在 → []。"""
    db.init_db()
    row = db.create_session(session_id="sess-nomatch", channel="test")
    sid = row["id"]
    db.add_message("msg-nomatch", sid, "user", "BTC 行情")
    assert db.search_messages("元力股份") == []
    assert db.search_messages("ZZZZ_noexist_99") == []


def test_search_finds_thinking_content() -> None:
    """thinking_content 字段也能搜(assistant 内部推理中的词)。

    WHY:有些回答看上去很短,但内部推理里包含了用户问题的关键词,
    用户搜关键词时应该也能命中这些「内心 OS」匹配。
    """
    db.init_db()
    row = db.create_session(session_id="sess-think", channel="test")
    sid = row["id"]
    msg = db.add_message(
        "msg-think-1",
        sid,
        "assistant",
        "回答",
        thinking_content="我先想想元力股份的基本面",
    )
    assert msg["id"] == "msg-think-1"
    results = db.search_messages("基本面")
    assert len(results) == 1
    assert results[0]["session_id"] == sid
    assert results[0]["role"] == "assistant"
    # 高亮打的是 thinking_content 列(没显式选 column 时默认 column 0 = content)
    # 这里不强要求 snippet 含 <mark>,只验命中即可 — THINK 内容也可能因
    # FTS5 snippet 不跨列而纯 content 命中,但 row 已被搜到。
    assert results[0]["content"] == "回答"


def test_search_limit_caps_results() -> None:
    """limit 限制返回数量(防止用户超大匹配集撑爆 UI)。

    WHY:bm25 排序后默认 50 条够了,但用户搜宽泛词(hello / 测试)可能
    命中成百上千条 — UI 渲染不可控,必须可截断。
    """
    db.init_db()
    row = db.create_session(session_id="sess-limit", channel="test")
    sid = row["id"]
    for i in range(5):
        db.add_message(f"msg-limit-{i}", sid, "user", f"BTC 行情第{i}次")
    results = db.search_messages("BTC", limit=3)
    assert len(results) == 3
    # 默认 limit 是 50
    results_default = db.search_messages("BTC")
    assert len(results_default) == 5
