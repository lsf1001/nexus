"""Regression test for the 2026-07-10 21:45 fact-check bug.

BUG 背景:
    On 2026-07-10 21:45 Asia/Shanghai, Nexus emitted natural-language text
    "明天是2026年7月11日 星期五" while the calendar said 2026-07-11 is 星期六.
    The HTML body still rendered 星期六 because that came from a deterministic
    timestamp formatter, but the model-side claim was a factual hallucination
    that contradicted the rendered date. This kind of contradiction must NEVER
    reach the user again.

为什么这组测试用 grep 找得到:
    文件名带 ``2026_07_10`` + 模块 docstring 含 ``session_id``,事故复盘时
    一行 ``grep -r 2026_07_10 tests/`` 就能召回。

关键事实(写死):
    - date(2026, 7, 11).weekday() == 5  → 星期六(Saturday)
    - 2026-07-10 是星期五,Asia/Shanghai 的"明天"指向 2026-07-11
    - DateWeekdayVerifier 是**确定性**纯函数,不调 datetime.now(),
      直接根据 claim 里的日期字符串算 weekday —— 所以本测试不需要
      freeze clock;但仍以 fixture 形式标记原 incident 的时刻,便于
      调试时一眼看出"这是哪条事故线"。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from nexus.backend import db as _db
from nexus.backend.agents.middleware.fact_check import (
    FactCheckError,
    FactCheckMiddleware,
)
from nexus.backend.fact_check.pipeline import FactCheckPipeline, FactCheckReport

# 原始事故中 LLM 输出的那句错误自然语言(逐字保留,不许改)
BUG_SENTENCE = "明天是2026年7月11日 星期五"
CORRECT_SENTENCE = "明天是2026年7月11日 星期六"


@dataclass(frozen=True)
class _FakeResponse:
    """LangChain AIMessage 风格的最小响应对象,供 middleware 抽 content。"""

    content: str


@dataclass(frozen=True)
class _IncidentMeta:
    """事故现场标记 — 任何事故复盘工具/文档生成脚本能直接读这玩意。"""

    incident_at: str = "2026-07-10T21:45:00+08:00"
    session_id: str = "1b286881-cef1-4d70-85c4-9a9fb0f6195a"
    buggy_claim: str = BUG_SENTENCE
    expected_weekday: str = "星期六"
    wrong_weekday_emitted: str = "星期五"
    repro_method: str = "FactCheckPipeline.check() with verbatim buggy sentence"


INCIDENT = _IncidentMeta()


class TestBugRegression:
    """五件套:日历事实 / pipeline 拒错 / middleware 抛错 / 正确句放行 / 审计落库。"""

    def test_calendar_facts_for_2026_07_11(self) -> None:
        """把日历真相钉死:2026-07-11 是星期六,不是星期五。

        若此测试挂了 → 整个 fact-check 链需要复审(可能是系统换历法了,
        也可能是 Python datetime 行为变了,极不可能)。
        """
        # Python's datetime.weekday(): Monday=0, ..., Saturday=5, Sunday=6
        assert date(2026, 7, 11).weekday() == 5, "2026-07-11 must be Saturday"
        assert date(2026, 7, 10).weekday() == 4, "2026-07-10 must be Friday"

        # 中文映射必须命中 mcp/date_utils.weekday_of
        from nexus.backend.mcp.date_utils import weekday_of

        assert weekday_of("2026-07-11") == "星期六"
        assert weekday_of("2026-07-10") == "星期五"

    def test_wrong_sentence_caught_by_pipeline(self) -> None:
        """原始事故的错句必须被 FactCheckPipeline 标记为冲突。

        这是 T13 端到端验证 —— extractor 应抽出 "2026年7月11日 星期五",
        verifier 应判 verdict="conflict",report.has_conflict 必须为 True。
        """
        report = FactCheckPipeline().check(BUG_SENTENCE)
        assert isinstance(report, FactCheckReport)
        assert report.has_conflict is True, (
            f"fact-check 回归了:错句 '{BUG_SENTENCE}' 没被识别为冲突。"
            f"实际 conflicts={[r.claim.raw_text for r in report.conflicts]}"
        )
        kinds = [r.claim.kind for r in report.conflicts]
        assert "date_weekday" in kinds, f"expected date_weekday conflict, got kinds={kinds}"
        # 进一步锁:这条冲突必须正好对应 BUG_SENTENCE 本身
        conflict_texts = [r.claim.raw_text for r in report.conflicts]
        assert any("2026年7月11日" in t and "星期五" in t for t in conflict_texts), (
            f"expected original buggy claim in conflicts, got {conflict_texts}"
        )

    def test_wrong_sentence_caught_by_middleware(self) -> None:
        """Middleware 层(fail_strategy='closed')必须抛 FactCheckError。

        不能只在 pipeline 层挡 —— 必须确认 wire-it 后,deepagents 主路径
        也会被拦住。
        """
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict[str, Any] = {"messages": []}

        async def fake_handler(req: Any) -> _FakeResponse:
            return _FakeResponse(content=BUG_SENTENCE)

        with pytest.raises(FactCheckError) as exc_info:
            asyncio.run(mw.wrap_model_call(request, fake_handler))

        msg = str(exc_info.value)
        # 错误信息必须含 fact-check 关键字 + 冲突事实(便于排障)
        lowered = msg.lower()
        assert "fact-check" in lowered or "冲突" in msg or "conflict" in lowered, (
            f"FactCheckError message must surface the failure cause, got: {msg!r}"
        )
        assert "星期五" in msg and "星期六" in msg, (
            f"FactCheckError must surface claimed vs actual weekday, got: {msg!r}"
        )

    def test_correct_sentence_passes_through(self) -> None:
        """对照实验:正确版本必须**不**抛 FactCheckError。"""
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict[str, Any] = {"messages": []}

        async def fake_handler(req: Any) -> _FakeResponse:
            return _FakeResponse(content=CORRECT_SENTENCE)

        # 不应该抛任何异常
        result = asyncio.run(mw.wrap_model_call(request, fake_handler))
        assert isinstance(result, _FakeResponse)
        assert result.content == CORRECT_SENTENCE

    def test_bug_sentence_audit_trail_persisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bug 句触发中间件时,save_quality_score 必须被调用且参数正确。

        验证 T12 落库链路接通:
            status='fail' / fact_check_claims 非空 / fact_check_latency_ms ≥ 0
        """
        captured: list[dict[str, Any]] = []

        def fake_save_quality_score(**kwargs: Any) -> None:
            captured.append(kwargs)

        # WHY: middleware 内部 `from nexus.backend import db as _db`,monkeypatch
        # 改模块属性必须在同一引用上 — conftest 的 isolate_runtime_state 已
        # 把 db_path 重定向到 tmp_path,真实 DB 不会污染。
        monkeypatch.setattr(_db, "save_quality_score", fake_save_quality_score)

        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict[str, Any] = {"messages": []}

        async def fake_handler(req: Any) -> _FakeResponse:
            return _FakeResponse(content=BUG_SENTENCE)

        with pytest.raises(FactCheckError):
            asyncio.run(mw.wrap_model_call(request, fake_handler))

        assert captured, "save_quality_score 必须至少被调用一次(失败路径也要落 audit)"
        kw = captured[-1]
        assert kw.get("fact_check_status") == "fail", kw
        assert kw.get("fact_check_claims"), "fact_check_claims 必须非空(audit trail 内容)"
        assert kw.get("fact_check_latency_ms") is not None
        assert kw["fact_check_latency_ms"] >= 0
        # rubric 必须是 fact_check,便于按 rubric 查询
        assert kw.get("rubric") == "fact_check", kw


# 把事故标记也以 module-level dict 暴露,grep 友好
TEST_METADATA = {
    "incident_at": INCIDENT.incident_at,
    "session_id": INCIDENT.session_id,
    "buggy_claim": INCIDENT.buggy_claim,
    "expected_weekday": INCIDENT.expected_weekday,
    "wrong_weekday_emitted": INCIDENT.wrong_weekday_emitted,
    "repro_method": INCIDENT.repro_method,
}
