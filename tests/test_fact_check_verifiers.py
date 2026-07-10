"""Tests for fact_check.verifiers."""

import pytest

from nexus.backend.fact_check.extractors import FactClaim
from nexus.backend.fact_check.verifiers import DateWeekdayVerifier, MathVerifier, UnitsVerifier


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


class TestMathVerifier:
    def test_simple_addition_correct(self):
        claim = FactClaim(
            kind="math",
            raw_text="23 + 32 = 55",
            expression="23 + 32",
            claimed_result="55",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.expected_value == 55.0
        assert result.actual_value == 55.0

    def test_addition_wrong(self):
        claim = FactClaim(
            kind="math",
            raw_text="23 + 32 = 56",
            expression="23 + 32",
            claimed_result="56",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "conflict"
        assert result.expected_value == 55.0
        assert result.actual_value == 56.0

    def test_multiplication_with_units(self):
        claim = FactClaim(
            kind="math",
            raw_text="1.5L × 2 = 3L",
            expression="1.5L × 2",
            claimed_result="3L",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.expected_value == 3.0
        assert result.actual_value == 3.0

    def test_division(self):
        claim = FactClaim(
            kind="math",
            raw_text="100 / 4 = 25",
            expression="100 / 4",
            claimed_result="25",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_chinese_operators(self):
        claim = FactClaim(
            kind="math",
            raw_text="100 乘以 2 等于 200",
            expression="100 乘以 2",
            claimed_result="200",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_unsafe_expression_rejected(self):
        claim = FactClaim(
            kind="math",
            raw_text="__import__('os').system('rm -rf /') = 0",
            expression="__import__('os').system('rm -rf /')",
            claimed_result="0",
        )
        result = MathVerifier().verify(claim)
        assert result.verdict == "error"


class TestUnitsVerifier:
    def test_correct_conversion_passes(self):
        claim = FactClaim(
            kind="unit",
            raw_text="100°C = 212°F",
            claimed_value=100.0,
            claimed_result="212",
            from_unit="C",
            to_unit="F",
        )
        result = UnitsVerifier().verify(claim)
        assert result.verdict == "ok"
        assert result.expected_value == pytest.approx(212.0, abs=0.01)
        assert result.actual_value == 212.0

    def test_wrong_conversion_conflicts(self):
        claim = FactClaim(
            kind="unit",
            raw_text="100°C = 200°F",
            claimed_value=100.0,
            claimed_result="200",
            from_unit="C",
            to_unit="F",
        )
        result = UnitsVerifier().verify(claim)
        assert result.verdict == "conflict"

    def test_km_to_mile_correct(self):
        claim = FactClaim(
            kind="unit",
            raw_text="1 km = 0.621371 mile",
            claimed_value=1.0,
            claimed_result="0.621371",
            from_unit="km",
            to_unit="mile",
        )
        result = UnitsVerifier().verify(claim)
        assert result.verdict == "ok"

    def test_incompatible_units_returns_error(self):
        claim = FactClaim(
            kind="unit",
            raw_text="5 kg = 5 m",
            claimed_value=5.0,
            claimed_result="5",
            from_unit="kg",
            to_unit="m",
        )
        result = UnitsVerifier().verify(claim)
        assert result.verdict == "error"
