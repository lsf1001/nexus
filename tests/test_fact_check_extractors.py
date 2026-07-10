"""Tests for fact_check.extractors."""

import pytest

from nexus.backend.fact_check.extractors import (
    DateWeekdayExtractor,
    MathExtractor,
    UnitsExtractor,
)


class TestDateWeekdayExtractor:
    def test_extracts_chinese_full_date_with_weekday(self):
        text = "明天是 2026年7月11日 星期六"
        claims = DateWeekdayExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].date_str == "2026年7月11日"
        assert claims[0].claimed_weekday_zh == "星期六"
        assert claims[0].raw_text == text

    def test_extracts_iso_date_with_weekday(self):
        text = "Plan for 2026-07-11 Saturday"
        claims = DateWeekdayExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].date_str == "2026-07-11"
        assert claims[0].claimed_weekday_zh == "星期六"

    def test_extracts_date_without_weekday(self):
        text = "Today is 2026-07-10"
        claims = DateWeekdayExtractor().extract(text)
        assert claims == []

    def test_extracts_multiple_claims(self):
        text = "From 2026-07-10 Friday to 2026-07-11 Saturday"
        claims = DateWeekdayExtractor().extract(text)
        assert len(claims) == 2

    def test_skips_invalid_weekday(self):
        text = "2026-07-11 星期八"
        claims = DateWeekdayExtractor().extract(text)
        assert all(c.claimed_weekday_zh != "星期八" for c in claims)


class TestMathExtractor:
    def test_extracts_addition(self):
        text = "23 + 32 = 55"
        claims = MathExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].expression == "23 + 32"
        assert claims[0].claimed_result == "55"

    def test_extracts_multiplication_with_units(self):
        text = "1.5L × 2 = 3L"
        claims = MathExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].expression == "1.5L × 2"
        assert claims[0].claimed_result == "3L"

    def test_skips_no_equals(self):
        text = "23 + 32"
        claims = MathExtractor().extract(text)
        assert claims == []

    def test_extracts_chinese_operators(self):
        text = "100 乘以 2 等于 200"
        claims = MathExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].claimed_result == "200"


class TestUnitsExtractor:
    def test_extracts_simple_conversion(self):
        text = "100°C = 212°F"
        claims = UnitsExtractor().extract(text)
        assert len(claims) == 1
        assert claims[0].claimed_value == 100.0
        assert claims[0].from_unit == "C"
        assert claims[0].to_unit == "F"
        assert float(claims[0].claimed_result) == 212.0

    def test_extracts_km_to_mile(self):
        text = "5 km = 3.107 mile"
        claims = UnitsExtractor().extract(text)
        assert len(claims) == 1
        assert float(claims[0].claimed_result) == pytest.approx(3.107, abs=0.01)
