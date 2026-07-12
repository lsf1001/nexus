"""Test that FactCheckMiddleware persists its results to quality_scores (T12).

Task 12 of the fact-check pipeline:
  - After awrap_model_call runs the fact-check pipeline, the results
    (status / latency / claims / conflicts) must be written to the
    quality_scores table via ``save_quality_score``.
  - This is the *first* caller of save_quality_score in production
    code (the function was orphaned by the 2026-06-29 QualityPipeline
    deletion).
  - DB errors must NOT break the agent run — wrap persistence in
    try/except and only log.
  - ``fail_strategy="closed"`` MUST still raise FactCheckError after
    persistence (no silent swallowing).

设计要点
--------

- 用 ``import as _db`` + ``monkeypatch.setattr(_db, "save_quality_score", ...)``:
  ``from db import save_quality_score`` 在 import 时绑值,monkeypatch 改不到;
  走 source module 属性替换才能在测试里替换(见
  ``feedback-monkeypatch-module-state``)。
- 用 ``temp_db`` fixture 把 DB 文件隔离到 ``tmp_path``,不污染真实 DB。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus.backend import db as _db
from nexus.backend.agents.middleware.fact_check import (
    FactCheckError,
    FactCheckMiddleware,
)


def _to_serializable(items: list[Any]) -> list[dict[str, Any]]:
    """把 dataclass 列表转为 dict 列表(JSON 可序列化)。"""
    out: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "__dataclass_fields__"):
            out.append(asdict(item))
        elif isinstance(item, dict):
            out.append(dict(item))
        else:
            out.append({"repr": str(item)})
    return out


@pytest.fixture
def patched_save(monkeypatch: pytest.MonkeyPatch):
    """替换 ``nexus.backend.db.save_quality_score`` 防止真写 DB。

    WHY source module: ``fact_check.py`` 用 ``from db import save_quality_score``,
    只 patch consumer 侧的本地名无法替换;必须 patch source module 的属性。
    """
    mock_save = MagicMock(return_value=1)
    monkeypatch.setattr(_db, "save_quality_score", mock_save)
    return mock_save


class TestFactCheckMiddlewarePersistence:
    """T12：FactCheckMiddleware 必须把结果持久化到 quality_scores."""

    @pytest.mark.asyncio
    async def test_conflict_case_persists_fact_check_row(self, patched_save: MagicMock):
        """日期/星期冲突时,必须写入 status='fail' 的行,再抛 FactCheckError。"""
        mw = FactCheckMiddleware(fail_strategy="closed")

        async def fake_handler(req):
            # 2026-07-11 是星期六,模型说"星期五"——冲突
            return {"content": "明天是2026年7月11日 星期五"}

        with pytest.raises(FactCheckError):
            await mw.awrap_model_call({}, fake_handler)

        assert patched_save.called, "save_quality_score must be called on conflict"
        kwargs = patched_save.call_args.kwargs
        assert kwargs["rubric"] == "fact_check"
        assert kwargs["fact_check_status"] == "fail"
        assert kwargs["score"] == 0.0
        assert kwargs["verdict"] == "reject"
        # claims/results 列表必须存在(可能为空也 OK,但字段必须传)
        assert "fact_check_claims" in kwargs
        assert "fact_check_results" in kwargs
        assert "fact_check_latency_ms" in kwargs
        assert kwargs["fact_check_latency_ms"] is not None
        assert kwargs["fact_check_latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_correct_case_persists_fact_check_row(self, patched_save: MagicMock):
        """事实正确时仍持久化(audit trail)。"""
        mw = FactCheckMiddleware(fail_strategy="closed")

        async def fake_handler(req):
            return {"content": "明天是2026年7月11日 星期六"}  # 正确

        result = await mw.awrap_model_call({}, fake_handler)
        assert result["content"] == "明天是2026年7月11日 星期六"

        assert patched_save.called, "save_quality_score must be called for audit trail"
        kwargs = patched_save.call_args.kwargs
        assert kwargs["fact_check_status"] == "pass"
        assert kwargs["score"] == 1.0
        assert kwargs["verdict"] == "accept"

    @pytest.mark.asyncio
    async def test_no_claims_does_not_persist(self, patched_save: MagicMock):
        """零事实声明的回复不应污染 quality_scores。"""
        mw = FactCheckMiddleware(fail_strategy="closed")

        async def fake_handler(req):
            return {"content": "好的,我帮你查一下"}  # 无日期/数学/汇率声明

        result = await mw.awrap_model_call({}, fake_handler)
        assert result["content"] == "好的,我帮你查一下"

        assert not patched_save.called, "save_quality_score must NOT be called when there are zero fact claims"

    @pytest.mark.asyncio
    async def test_fail_open_also_persists(self, patched_save: MagicMock):
        """fail-open 模式下,冲突依然写入 status='fail',只是不抛错。"""
        mw = FactCheckMiddleware(fail_strategy="open")

        async def fake_handler(req):
            return {"content": "明天是2026年7月11日 星期五"}

        result = await mw.awrap_model_call({}, fake_handler)
        assert result.get("_fact_check_warnings"), "fail-open must attach warnings"

        assert patched_save.called
        kwargs = patched_save.call_args.kwargs
        assert kwargs["fact_check_status"] == "fail"

    @pytest.mark.asyncio
    async def test_db_error_does_not_break_agent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """DB 写入失败时不能阻断 agent run;只 log warning。"""

        # 模拟 save 抛 sqlite 错误
        def boom(**_kwargs):
            raise RuntimeError("simulated DB failure")

        monkeypatch.setattr(_db, "save_quality_score", boom)

        mw = FactCheckMiddleware(fail_strategy="closed")

        async def fake_handler(req):
            return {"content": "明天是2026年7月11日 星期五"}  # 冲突

        # 仍然抛 FactCheckError(DB 失败只 log,不掩盖原错)
        with pytest.raises(FactCheckError):
            await mw.awrap_model_call({}, fake_handler)

    @pytest.mark.asyncio
    async def test_session_id_extracted_from_request(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """request 中带 HumanMessage metadata.session_id 时,持久化必须用上。"""
        from langchain_core.messages import HumanMessage

        captured: dict[str, Any] = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return 1

        monkeypatch.setattr(_db, "save_quality_score", capture)

        mw = FactCheckMiddleware(fail_strategy="closed")
        request = {
            "messages": [
                HumanMessage(
                    content="查一下明天日期",
                    additional_kwargs={"session_id": "sess-abc-123"},
                ),
            ],
        }

        async def fake_handler(req):
            return {"content": "明天是2026年7月11日 星期六"}  # 正确

        await mw.awrap_model_call(request, fake_handler)

        assert captured.get("session_id") == "sess-abc-123"
        assert captured.get("fact_check_status") == "pass"

    @pytest.mark.asyncio
    async def test_session_id_fallback_to_unknown(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """request 里取不到 session_id 时,默认 'unknown'(列 NOT NULL)。"""
        captured: dict[str, Any] = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return 1

        monkeypatch.setattr(_db, "save_quality_score", capture)

        mw = FactCheckMiddleware(fail_strategy="closed")

        async def fake_handler(req):
            return {"content": "明天是2026年7月11日 星期六"}

        await mw.awrap_model_call({}, fake_handler)  # 空 request,无 session_id

        assert captured.get("session_id") == "unknown"
        assert captured.get("fact_check_status") == "pass"


class TestFactCheckMiddlewarePersistenceWithRealDB:
    """集成路径:直接落 tmp SQLite,验证 row 真的能读回来。"""

    @pytest.fixture
    def temp_db(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        """用 tmp SQLite 跑 _create_tables 完整迁移。"""
        import sqlite3

        from nexus.backend.db import _create_tables

        db_path = tmp_path / "test.db"
        monkeypatch.setitem(_db.CONFIG, "db_path", str(db_path))
        monkeypatch.setattr(_db, "_INITED", False)
        conn = sqlite3.connect(str(db_path))
        _create_tables(conn)
        conn.commit()
        conn.close()
        yield db_path
        monkeypatch.setattr(_db, "_INITED", False)

    @pytest.mark.asyncio
    async def test_actually_writes_quality_scores_row(
        self,
        temp_db,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """不 mock save 时,row 必须真写进 tmp SQLite。"""
        import sqlite3

        # temp_db fixture 已经把 _db.CONFIG 指向 tmp_path,直接调真实 save
        mw = FactCheckMiddleware(fail_strategy="closed")

        async def fake_handler(req):
            return {"content": "明天是2026年7月11日 星期五"}

        with pytest.raises(FactCheckError):
            await mw.awrap_model_call({}, fake_handler)

        # 直接查 tmp SQLite,验证行真存在
        conn = sqlite3.connect(str(temp_db))
        row = conn.execute(
            "SELECT session_id, rubric, fact_check_status, fact_check_latency_ms "
            "FROM quality_scores ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        assert row is not None, "quality_scores row must exist"
        session_id, rubric, status, latency = row
        assert session_id == "unknown"  # request 没传,fallback
        assert rubric == "fact_check"
        assert status == "fail"
        assert latency is not None
        assert latency >= 0
