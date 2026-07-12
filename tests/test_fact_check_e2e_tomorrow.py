"""End-to-end test for the user-facing scenario '明天是星期几'.

A real user asks "明天是星期几?" and an LLM is supposed to answer using
the today/weekday_of tools. Two outcomes:

A. Correct answer ("星期二") → fact-check PASSES → response reaches user.
B. Wrong answer ("星期五") → fact-check CONFLICTS → FactCheckError raised,
   response blocked, audit trail written.

This test exercises BOTH paths to lock down the gate against the original
date/weekday failure mode that motivated the whole pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from nexus.backend.agents.middleware.fact_check import (
    FactCheckError,
    FactCheckMiddleware,
)
from nexus.backend.fact_check import FactCheckPipeline
from nexus.backend.mcp.date_utils import today as date_utils_today
from nexus.backend.mcp.date_utils import weekday_of as date_utils_weekday_of

# Test scenario: pin to a day far from 2026-07-10/11 to ensure tests aren't
# accidentally passing because of the original bug's specific date.
# Pick 2027-03-15 14:00 Shanghai → 2027-03-15 is a Monday, so 明天 is Tuesday.
SHANGHAI = ZoneInfo("Asia/Shanghai")
FROZEN_TODAY = datetime(2027, 3, 15, 14, 0, tzinfo=SHANGHAI)
FROZEN_TODAY_DATE = FROZEN_TODAY.date()
TOMORROW_DATE = datetime(2027, 3, 16, 14, 0, tzinfo=SHANGHAI).date()


class _FrozenDatetime(datetime):
    """datetime subclass that pretends it's always 2027-03-15 14:00 Shanghai.

    Only used via ``patch(...)`` of the symbol ``datetime`` inside the
    date_utils module (and a couple of friends). DateWeekdayVerifier was
    confirmed deterministic in T17, but for E2E we want maximum robustness
    in case the extractor / verifier ever grows to need today().
    """

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return FROZEN_TODAY.replace(tzinfo=None)
        return FROZEN_TODAY.astimezone(tz)


@pytest.fixture(autouse=True)
def frozen_clock():
    """Pin the system clock so date_utils.today() returns 2027-03-15."""
    with (
        patch(
            "nexus.backend.mcp.date_utils.datetime",
            _FrozenDatetime,
            create=True,
        ),
        patch(
            "nexus.backend.fact_check.extractors.datetime",
            _FrozenDatetime,
            create=True,
        ),
        patch(
            "nexus.backend.fact_check.verifiers.datetime",
            _FrozenDatetime,
            create=True,
        ),
    ):
        yield


class _StubResponse:
    """langchain-style response object exposing ``.content``."""

    def __init__(self, content: str) -> None:
        self.content = content


class TestCalendarBaseline:
    """Lock down the calendar truth for the test day."""

    def test_frozen_today_is_monday(self):
        assert FROZEN_TODAY_DATE.weekday() == 0  # Monday

    def test_tomorrow_is_tuesday(self):
        assert TOMORROW_DATE.weekday() == 1  # Tuesday

    def test_today_tool_returns_frozen_date(self):
        # mcp/date_utils.today() ignores its tz arg and always uses Shanghai.
        result = date_utils_today()
        assert result == FROZEN_TODAY_DATE.isoformat()  # "2027-03-15"

    def test_weekday_of_tomorrow_returns_tuesday(self):
        result = date_utils_weekday_of("2027-03-16")
        assert result == "星期二"


class TestCorrectAnswerPasses:
    """When the LLM emits a CORRECT tomorrow-weekday, the gate passes."""

    @pytest.fixture
    def correct_response(self) -> str:
        return "今天2027年3月15日是星期一,明天2027年3月16日 星期二。"

    def test_factcheck_pipeline_no_conflict(self, correct_response: str) -> None:
        report = FactCheckPipeline().check(correct_response)
        assert report.has_conflict is False, f"correct answer flagged as conflict: {report.conflicts}"

    def test_middleware_passes_through(self, correct_response: str) -> None:
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict = {"messages": []}

        async def handler(_req):
            return _StubResponse(correct_response)

        response = asyncio.run(mw.awrap_model_call(request, handler))
        assert response.content == correct_response

    def test_middleware_dict_response_passes_through(self, correct_response: str) -> None:
        """Dict-style responses (ModelResponse.to_dict shape) also flow."""
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict = {"messages": []}

        async def handler(_req):
            return {"content": correct_response}

        response = asyncio.run(mw.awrap_model_call(request, handler))
        assert response["content"] == correct_response

    def test_verify_claims_tool_returns_ok(self, correct_response: str) -> None:
        from nexus.backend.fact_check.langchain_tools import verify_claims

        result_str = asyncio.run(verify_claims.ainvoke({"text": correct_response}))
        result = result_str if isinstance(result_str, str) else str(result_str)
        # correct answer: ok=true in JSON, no conflict
        assert '"ok": true' in result or '"ok":true' in result, f"expected ok=true, got: {result}"


class TestWrongAnswerBlocked:
    """When the LLM emits the WRONG tomorrow-weekday, the gate raises."""

    @pytest.fixture
    def wrong_response(self) -> str:
        # 2027-03-16 is Tuesday, NOT Friday.
        return "明天2027年3月16日 星期五。"

    def test_factcheck_pipeline_catches_conflict(self, wrong_response: str) -> None:
        report = FactCheckPipeline().check(wrong_response)
        assert report.has_conflict is True
        assert report.claims_total >= 1
        # Must be a date_weekday conflict specifically.
        assert any(getattr(r.claim, "kind", None) == "date_weekday" for r in report.conflicts), (
            f"expected date_weekday conflict, got kinds={[getattr(r.claim, 'kind', None) for r in report.conflicts]}"
        )

    def test_middleware_raises_on_wrong(self, wrong_response: str) -> None:
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict = {"messages": []}

        async def handler(_req):
            return _StubResponse(wrong_response)

        with pytest.raises(FactCheckError):
            asyncio.run(mw.awrap_model_call(request, handler))

    def test_middleware_dict_response_raises_on_wrong(self, wrong_response: str) -> None:
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict = {"messages": []}

        async def handler(_req):
            return {"content": wrong_response}

        with pytest.raises(FactCheckError):
            asyncio.run(mw.awrap_model_call(request, handler))

    def test_fail_open_logs_but_passes(self, wrong_response: str, caplog) -> None:
        """fail_strategy='open': wrong answer passes but is logged + persisted."""
        mw = FactCheckMiddleware(fail_strategy="open")
        request: dict = {"messages": []}

        async def handler(_req):
            return _StubResponse(wrong_response)

        with caplog.at_level(logging.WARNING):
            response = asyncio.run(mw.awrap_model_call(request, handler))
        # Response still flows through (fail-open).
        assert response.content == wrong_response
        # The conflict was logged — the middleware emits
        # "FactCheckMiddleware open 放行：N 个冲突" at WARNING.
        assert any(
            "factcheckmiddleware" in r.getMessage().lower()
            or "冲突" in r.getMessage()
            or "fact-check" in r.getMessage().lower()
            for r in caplog.records
        ), f"expected warning log, got: {[r.getMessage() for r in caplog.records]}"


class TestRealUserQuestion:
    """Simulate the actual user query and verify both outcomes."""

    def test_realistic_query_correct_path(self) -> None:
        """User: '明天是星期几?' → LLM answers '星期二' → gate passes."""
        # A model that knows the date and uses tools computes the right answer.
        correct_answer = f"今天是 {FROZEN_TODAY_DATE.isoformat()} 星期一,明天是 {TOMORROW_DATE.isoformat()} 星期二。"
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict = {"messages": []}

        async def handler(_req):
            return _StubResponse(correct_answer)

        result = asyncio.run(mw.awrap_model_call(request, handler))
        assert result.content == correct_answer

    def test_realistic_query_hallucination_blocked(self) -> None:
        """User: '明天是星期几?' → LLM hallucinates '星期五' → blocked."""
        # A model with no calendar / no tools hallucinating — the original
        # failure mode that motivated the whole pipeline.
        hallucinated_answer = "明天是 2027年3月16日 星期五。"  # 2027-03-16 is Tuesday, NOT Friday
        mw = FactCheckMiddleware(fail_strategy="closed")
        request: dict = {"messages": []}

        async def handler(_req):
            return _StubResponse(hallucinated_answer)

        with pytest.raises(FactCheckError) as exc_info:
            asyncio.run(mw.awrap_model_call(request, handler))
        # The error message should reference the date/weekday conflict.
        assert exc_info.value.conflicts, "FactCheckError must carry conflict list"
        conflict = exc_info.value.conflicts[0]
        assert conflict["kind"] == "date_weekday"
        assert "星期五" in str(conflict["claimed"])
        assert "星期二" in str(conflict["actual"])


class TestExtractorFormatCoverage:
    """Lock down the formats the DateWeekdayExtractor actually recognizes.

    The extractor's regexes only fire on explicit date + weekday pairs in
    either 中文年月日 or ISO + English weekday form. These tests pin that
    behavior so we don't silently break coverage when changing the regex.
    """

    def test_zh_format_correct_no_conflict(self) -> None:
        report = FactCheckPipeline().check("明天是 2027年3月16日 星期二")
        assert report.has_conflict is False

    def test_zh_format_wrong_caught(self) -> None:
        report = FactCheckPipeline().check("明天是 2027年3月16日 星期五")
        assert report.has_conflict is True

    def test_iso_format_correct_no_conflict(self) -> None:
        report = FactCheckPipeline().check("2027-03-16 Tuesday")
        assert report.has_conflict is False

    def test_iso_format_wrong_caught(self) -> None:
        report = FactCheckPipeline().check("2027-03-16 Friday")
        assert report.has_conflict is True

    def test_pure_prose_no_date_passes(self) -> None:
        """Pure prose without date/weekday passes untouched."""
        report = FactCheckPipeline().check("今天天气不错,适合出门散步,记得带伞。")
        assert report.has_conflict is False
        assert report.claims_total == 0

    def test_bare_weekday_without_date_passes(self) -> None:
        """'明天是星期三' alone (no explicit date) — extractor can't pin it,
        so it falls through with no claim → no conflict (verifier can't
        know it's wrong without an explicit date)."""
        report = FactCheckPipeline().check("明天是星期三")
        # No explicit date → no claim extracted → no conflict.
        assert report.has_conflict is False
        assert report.claims_total == 0


class TestVerifyClaimsToolRoundTrip:
    """The ``verify_claims`` tool LLM sees: round-trip both outcomes."""

    def test_verify_claims_ok_for_correct(self) -> None:
        from nexus.backend.fact_check.langchain_tools import verify_claims

        text = "今天是 2027年3月15日 星期一,明天是 2027年3月16日 星期二。"
        result = asyncio.run(verify_claims.ainvoke({"text": text}))
        result_str = result if isinstance(result, str) else str(result)
        assert '"ok": true' in result_str or '"ok":true' in result_str
        assert '"conflicts_total": 0' in result_str

    def test_verify_claims_conflict_for_wrong(self) -> None:
        from nexus.backend.fact_check.langchain_tools import verify_claims

        text = "明天是 2027年3月16日 星期五。"  # wrong
        result = asyncio.run(verify_claims.ainvoke({"text": text}))
        result_str = result if isinstance(result, str) else str(result)
        assert '"ok": false' in result_str or '"ok":false' in result_str
        assert '"conflicts_total": 1' in result_str
