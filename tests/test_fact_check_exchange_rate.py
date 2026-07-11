"""Tests for fact_check.exchange_rate."""

import time

import pytest

from nexus.backend.fact_check.exchange_rate import (
    ExchangeRateCache,
    clear_cache,
    fetch_rate,
)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_cache()
    yield
    clear_cache()


class TestExchangeRateCache:
    def test_returns_cached_value_within_ttl(self):
        cache = ExchangeRateCache(ttl_seconds=60)
        cache.set("USD", {"rate": 7.20, "fetched_at": time.time()})
        rate = cache.get("USD")
        assert rate == pytest.approx(7.20, abs=0.001)

    def test_expired_entry_returns_none(self):
        cache = ExchangeRateCache(ttl_seconds=0.01)
        cache.set("USD", {"rate": 7.20, "fetched_at": time.time() - 1})
        assert cache.get("USD") is None


class TestFetchRate:
    def test_fetch_success(self, monkeypatch):
        async def mock_fetch(url):
            return {"rates": {"CNY": 7.20}}

        monkeypatch.setattr(
            "nexus.backend.fact_check.exchange_rate._fetch_api",
            mock_fetch,
        )
        rate = fetch_rate("USD", "CNY", api_key="dummy")
        assert rate == pytest.approx(7.20, abs=0.001)

    def test_fetch_uses_cache(self, monkeypatch):
        async def mock_fetch(url):
            return {"rates": {"CNY": 7.20}}

        monkeypatch.setattr(
            "nexus.backend.fact_check.exchange_rate._fetch_api",
            mock_fetch,
        )
        rate1 = fetch_rate("USD", "CNY", api_key="dummy")

        call_count = [0]

        async def counting_fetch(url):
            call_count[0] += 1
            return {"rates": {"CNY": 999.99}}

        monkeypatch.setattr(
            "nexus.backend.fact_check.exchange_rate._fetch_api",
            counting_fetch,
        )
        rate2 = fetch_rate("USD", "CNY", api_key="dummy")
        assert rate1 == rate2
        assert call_count[0] == 0
