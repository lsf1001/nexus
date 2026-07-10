"""Tests for fact_check.verifiers."""

from nexus.backend.fact_check.extractors import FactClaim
from nexus.backend.fact_check.verifiers import DateWeekdayVerifier


class TestDateWeekdayVerifier:
    def test_correct_weekday_passes(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026年7月11日 星期六",
            date_str="2026年7月11日",
            claimed_weekday_zh="星期六",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.actual_weekday_zh == "星期六"

    def test_wrong_weekday_conflicts(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026年7月11日 星期五",
            date_str="2026年7月11日",
            claimed_weekday_zh="星期五",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "conflict"
        assert result.claimed_weekday_zh == "星期五"
        assert result.actual_weekday_zh == "星期六"

    def test_iso_format(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026-07-11 Saturday",
            date_str="2026-07-11",
            claimed_weekday_zh="星期六",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_invalid_date_returns_error(self):
        claim = FactClaim(
            kind="date_weekday",
            raw_text="2026年13月45日 星期一",
            date_str="2026年13月45日",
            claimed_weekday_zh="星期一",
        )
        result = DateWeekdayVerifier().verify(claim)
        assert result.verdict == "error"
