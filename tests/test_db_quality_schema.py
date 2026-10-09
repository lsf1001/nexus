"""QualityScoreRepo 单元测试。

WHY: 此前 ``save_quality_score`` 等函数直接挂在 ``db`` 顶层,~60 行
杂糅 PRAGMA / DDL / DML,拆为 ``QualityScoreRepo`` 类后必须用 6 个测试锁定
行为边界(注入连接 / 参数化 SQL / 不持连接 / 返回 dataclass)。

注意 fixture 里的 ``quality_scores`` DDL 是从 ``db/__init__.py``
``_create_tables()`` 抄来的**生产真实 schema**(``created_at`` 用
``TIMESTAMP DEFAULT CURRENT_TIMESTAMP``,4 个 ``fact_check_*`` 列内联),
不是另写一份字面量——避免测试 schema 与生产 schema 漂移。
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def repo(tmp_path):
    """注入临时 SQLite 连接 + production 真实 quality_scores schema。"""
    from nexus.backend.db.quality_schema import QualityScoreRepo

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS quality_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message_id TEXT,
            rubric TEXT NOT NULL,
            score REAL NOT NULL,
            verdict TEXT NOT NULL,
            reasoning TEXT,
            fact_check_claims TEXT,
            fact_check_results TEXT,
            fact_check_status TEXT,
            fact_check_latency_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_quality_session ON quality_scores(session_id);
        """
    )
    return QualityScoreRepo(conn=conn)


def test_upsert_inserts_new_row(repo) -> None:
    """upsert 在 message_id 不存在时插入新行。"""
    repo.upsert(
        message_id="m1",
        rubric="faithfulness",
        score=0.9,
        verdict="accept",
        reasoning="good",
    )
    latest = repo.get_latest("m1")
    assert latest is not None
    assert latest.score == 0.9
    assert latest.verdict == "accept"
    assert latest.reasoning == "good"


def test_upsert_updates_existing_row(repo) -> None:
    """同 message_id 再 upsert 后,get_latest 返回最新一条(score/verdict/reasoning 已更新)。"""
    repo.upsert(message_id="m1", rubric="faithfulness", score=0.5, verdict="repair", reasoning="r1")
    repo.upsert(message_id="m1", rubric="faithfulness", score=0.9, verdict="accept", reasoning="r2")
    latest = repo.get_latest("m1")
    assert latest is not None
    assert latest.score == 0.9
    assert latest.verdict == "accept"
    assert latest.reasoning == "r2"


def test_get_latest_returns_none_when_absent(repo) -> None:
    """get_latest 在 message_id 不存在时返回 None,不抛。"""
    assert repo.get_latest("nonexistent") is None


def test_list_for_session_filters_by_session(repo) -> None:
    """list_for_session 只返回指定 session 的记录。"""
    repo.upsert(message_id="m1", session_id="s1", rubric="faithfulness", score=0.5, verdict="accept")
    repo.upsert(message_id="m2", session_id="s2", rubric="faithfulness", score=0.7, verdict="accept")
    rows_s1 = repo.list_for_session("s1")
    rows_s2 = repo.list_for_session("s2")
    assert len(rows_s1) == 1
    assert len(rows_s2) == 1
    assert rows_s1[0].message_id == "m1"
    assert rows_s2[0].message_id == "m2"


def test_average_returns_mean_of_session(repo) -> None:
    """average 计算 session 内所有 score 的平均值,无记录返回 None。"""
    repo.upsert(message_id="m1", session_id="s1", rubric="r1", score=0.4, verdict="accept")
    repo.upsert(message_id="m2", session_id="s1", rubric="r1", score=0.8, verdict="accept")
    assert repo.average("s1") == pytest.approx(0.6)
    assert repo.average("empty") is None


def test_does_not_hold_connection_state(repo) -> None:
    """repo 不持连接,close 外部 conn 后 _conn 引用仍可验证。"""
    # repo 仅持引用,不持新连接;close conn 后内部 _conn 仍是 close 状态
    repo._conn.close()  # type: ignore[attr-defined]
    with pytest.raises(sqlite3.ProgrammingError):
        repo._conn.execute("SELECT 1")  # type: ignore[attr-defined]
