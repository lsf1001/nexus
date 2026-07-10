"""Tests for fact_check.units."""

import pytest

from nexus.backend.fact_check.units import convert, supported_units


class TestConvert:
    def test_celsius_to_fahrenheit(self):
        assert convert(100, "C", "F") == pytest.approx(212.0, abs=0.01)

    def test_fahrenheit_to_celsius(self):
        assert convert(32, "F", "C") == pytest.approx(0.0, abs=0.01)

    def test_km_to_mile(self):
        assert convert(1, "km", "mile") == pytest.approx(0.621371, abs=0.001)

    def test_kg_to_lb(self):
        assert convert(1, "kg", "lb") == pytest.approx(2.20462, abs=0.001)

    def test_meter_to_foot(self):
        assert convert(1, "m", "ft") == pytest.approx(3.28084, abs=0.001)

    def test_incompatible_units_raises(self):
        with pytest.raises(ValueError, match="Incompatible"):
            convert(1, "kg", "m")

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            convert(1, "foo", "bar")


class TestSupportedUnits:
    def test_returns_dict(self):
        units = supported_units()
        assert "C" in units
        assert "F" in units
        assert "kg" in units
