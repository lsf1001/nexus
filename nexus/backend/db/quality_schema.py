"""quality_scores 表的 CRUD 封装。

WHY 抽类:原 ``save_quality_score`` 是 ~60 行 module-level 函数,
混 SQL + 序列化 + 默认值,不可注入、不可测试。拆为 ``QualityScoreRepo``
后,所有 SQL 强制参数化(``?``),构造注入 ``conn``(不持新连接),
返回 dataclass ``QualityScore``(不返回 dict)。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityScore:
    """单条 quality_scores 表记录。"""

    id: int
    session_id: str
    message_id: str | None
    rubric: str
    score: float
    verdict: str
    reasoning: str
    fact_check_claims: list[dict[str, Any]] | None
    fact_check_results: list[dict[str, Any]] | None
    fact_check_status: str | None
    fact_check_latency_ms: int | None
    created_at: str


class QualityScoreRepo:
    """quality_scores 表 CRUD。

    设计约束:
      - 不持新连接(用构造注入的 ``conn``,不调 ``sqlite3.connect``)
      - 强制参数化 SQL(``?`` 占位,禁止 f-string 拼 SQL)
      - 返回 dataclass ``QualityScore``(不返回 ``sqlite3.Row`` 或 dict)
      - 不做 schema 迁移(由 ``db/__init__.py`` 负责 ``_ensure_column``)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        message_id: str | None = None,
        session_id: str = "",
        rubric: str,
        score: float,
        verdict: str,
        reasoning: str = "",
        fact_check_claims: list[dict[str, Any]] | None = None,
        fact_check_results: list[dict[str, Any]] | None = None,
        fact_check_status: str | None = None,
        fact_check_latency_ms: int | None = None,
    ) -> int:
        """插入一条质量评分。

        Args:
            message_id: 关联的 assistant 消息 ID。
            session_id: 所属会话。
            rubric: 评分维度名。
            score: 0.0-1.0。
            verdict: ``"accept"`` / ``"repair"`` / ``"reject"``。
            reasoning: 评分理由。
            fact_check_*: 4 个 fact-check 相关字段(可空)。

        Returns:
            新插入行的 id。

        Note:
            方法名为 ``upsert`` 但当前实现是纯 ``INSERT``(每次调用追加一行),
            与历史 ``save_quality_score`` 行为一致。同一 ``message_id`` 的多条记录
            由 ``get_latest`` 按 ``id DESC`` 取最新一条来收敛。若将来改成真正的
            ``INSERT ... ON CONFLICT DO UPDATE``,需给 ``quality_scores`` 加
            ``message_id`` 唯一索引,届时 ``test_upsert_updates_existing_row``
            的断言仍然成立。
        """
        claims_json = json.dumps(fact_check_claims, ensure_ascii=False) if fact_check_claims is not None else None
        results_json = json.dumps(fact_check_results, ensure_ascii=False) if fact_check_results is not None else None

        cur = self._conn.execute(
            """
            INSERT INTO quality_scores
                (session_id, message_id, rubric, score, verdict, reasoning,
                 fact_check_claims, fact_check_results, fact_check_status, fact_check_latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                message_id,
                rubric,
                score,
                verdict,
                reasoning,
                claims_json,
                results_json,
                fact_check_status,
                fact_check_latency_ms,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def get_latest(self, message_id: str) -> QualityScore | None:
        """拿指定 message_id 的最新一条;不存在返回 None。"""
        cur = self._conn.execute(
            "SELECT * FROM quality_scores WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (message_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_score(row)

    def list_for_session(self, session_id: str, *, limit: int = 50) -> list[QualityScore]:
        """列出 session 内最近 ``limit`` 条评分。"""
        cur = self._conn.execute(
            "SELECT * FROM quality_scores WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return [self._row_to_score(row) for row in cur.fetchall()]

    def average(self, session_id: str) -> float | None:
        """计算 session 内 score 平均值;无记录返回 None。"""
        cur = self._conn.execute(
            "SELECT AVG(score) AS avg FROM quality_scores WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    @staticmethod
    def _row_to_score(row: sqlite3.Row) -> QualityScore:
        """sqlite3.Row → QualityScore dataclass(JSON 列反序列化)。"""
        claims_raw = row["fact_check_claims"]
        results_raw = row["fact_check_results"]
        return QualityScore(
            id=row["id"],
            session_id=row["session_id"],
            message_id=row["message_id"],
            rubric=row["rubric"],
            score=row["score"],
            verdict=row["verdict"],
            reasoning=row["reasoning"] or "",
            fact_check_claims=json.loads(claims_raw) if claims_raw else None,
            fact_check_results=json.loads(results_raw) if results_raw else None,
            fact_check_status=row["fact_check_status"],
            fact_check_latency_ms=row["fact_check_latency_ms"],
            created_at=row["created_at"],
        )
