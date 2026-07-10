"""DB schema 测试：fact-check pipeline 在 quality_scores 表新增的列。

Task 11 of fact-check-pipeline:
  - 给 quality_scores 加 4 列 (fact_check_claims / fact_check_results / fact_check_status / fact_check_latency_ms)
  - 扩展 save_quality_score() 签名接受 4 个新可选 kwarg
  - 旧调用模式（不带新 kwarg）仍能写入，新列自动为 NULL
  - JSON 列用 json.dumps 序列化为 TEXT 存储
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from nexus.backend import db
from nexus.backend.db import _create_tables, save_quality_score


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """每个测试用独立临时 DB 文件 + 跑完整 _create_tables 迁移。"""
    db_path = tmp_path / "test.db"
    # 把 CONFIG.db_path 指向 tmp_path,让 get_db() 也走这里
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    # 重置 _INITED 让 _create_tables 实际跑一遍 (含 _ensure_column 迁移)
    monkeypatch.setattr(db, "_INITED", False)
    # 跑一遍完整迁移
    conn = sqlite3.connect(str(db_path))
    _create_tables(conn)
    conn.commit()
    conn.close()
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


class TestFactCheckColumns:
    """quality_scores 必须包含 fact-check pipeline 所需的 4 列。"""

    def test_quality_scores_has_fact_check_columns(self, temp_db):
        """4 个新列必须存在（PRAGMA table_info 验证）。"""
        conn = sqlite3.connect(str(temp_db))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(quality_scores)").fetchall()}
        conn.close()
        assert "fact_check_claims" in cols, "missing fact_check_claims column"
        assert "fact_check_results" in cols, "missing fact_check_results column"
        assert "fact_check_status" in cols, "missing fact_check_status column"
        assert "fact_check_latency_ms" in cols, "missing fact_check_latency_ms column"

    def test_save_quality_score_accepts_fact_check_kwargs(self, temp_db):
        """save_quality_score 必须接受 4 个新 kwarg 并写入行。"""
        save_quality_score(
            session_id="sess-fc",
            message_id="msg-fc-1",
            rubric="fact_check",
            score=1.0,
            verdict="accept",
            reasoning="all claims correct",
            fact_check_claims=[{"claim": "明天是星期六", "source": "calendar"}],
            fact_check_results=[{"claim": "明天是星期六", "status": "ok", "confidence": 0.95}],
            fact_check_status="pass",
            fact_check_latency_ms=42,
        )

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute(
            "SELECT fact_check_status, fact_check_latency_ms, fact_check_claims, fact_check_results "
            "FROM quality_scores WHERE message_id = ?",
            ("msg-fc-1",),
        ).fetchone()
        conn.close()

        assert row is not None, "row not inserted"
        status, latency, claims_json, results_json = row
        assert status == "pass"
        assert latency == 42

        # JSON 列用 TEXT 存,读回能反序列化
        claims = json.loads(claims_json)
        results = json.loads(results_json)
        assert claims == [{"claim": "明天是星期六", "source": "calendar"}]
        assert results == [{"claim": "明天是星期六", "status": "ok", "confidence": 0.95}]

    def test_save_quality_score_works_without_fact_check_kwargs(self, temp_db):
        """向后兼容：旧调用模式（不带 fact_check_* kwarg）必须仍能写入,新列自动 NULL。"""
        save_quality_score(
            session_id="sess-legacy",
            message_id="msg-legacy-1",
            rubric="faithfulness",
            score=0.95,
            verdict="accept",
            reasoning="ok",
        )

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute(
            "SELECT fact_check_status, fact_check_latency_ms, fact_check_claims, fact_check_results "
            "FROM quality_scores WHERE message_id = ?",
            ("msg-legacy-1",),
        ).fetchone()
        conn.close()

        assert row is not None, "row not inserted"
        status, latency, claims_json, results_json = row
        assert status is None
        assert latency is None
        assert claims_json is None
        assert results_json is None

    def test_partial_fact_check_kwargs_allowed(self, temp_db):
        """边界条件：只传部分新 kwarg 时,其余新列必须为 NULL,行为不崩。"""
        save_quality_score(
            session_id="sess-partial",
            message_id="msg-partial-1",
            rubric="fact_check",
            score=0.8,
            verdict="repair",
            reasoning="one claim uncertain",
            fact_check_status="partial",
            # fact_check_claims / fact_check_results / fact_check_latency_ms 故意不传
        )

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute(
            "SELECT fact_check_status, fact_check_latency_ms, fact_check_claims, fact_check_results "
            "FROM quality_scores WHERE message_id = ?",
            ("msg-partial-1",),
        ).fetchone()
        conn.close()

        assert row is not None
        status, latency, claims_json, results_json = row
        assert status == "partial"
        assert latency is None
        assert claims_json is None
        assert results_json is None

    def test_migration_is_idempotent(self, temp_db):
        """幂等：再次跑 _create_tables 不会因 ALTER TABLE 已存在的列报错。"""
        conn = sqlite3.connect(str(temp_db))
        _create_tables(conn)  # 第 2 次
        _create_tables(conn)  # 第 3 次
        conn.commit()

        cols = {row[1] for row in conn.execute("PRAGMA table_info(quality_scores)").fetchall()}
        conn.close()
        assert "fact_check_claims" in cols
        assert "fact_check_results" in cols
        assert "fact_check_status" in cols
        assert "fact_check_latency_ms" in cols
