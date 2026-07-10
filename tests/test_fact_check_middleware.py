"""Tests for FactCheckMiddleware."""

import pytest

from nexus.backend.agents.middleware.fact_check import (
    FactCheckError,
    FactCheckMiddleware,
)


class TestFactCheckMiddleware:
    @pytest.mark.asyncio
    async def test_passes_clean_output(self):
        async def handler(req):
            return {"content": "明天是 2026年7月11日 星期六"}

        mw = FactCheckMiddleware()
        result = await mw.wrap_model_call({}, handler)
        assert result["content"] == "明天是 2026年7月11日 星期六"

    @pytest.mark.asyncio
    async def test_raises_on_conflict_fail_closed(self):
        async def handler(req):
            return {"content": "明天是 2026年7月11日 星期五"}  # wrong

        mw = FactCheckMiddleware(fail_strategy="closed")
        with pytest.raises(FactCheckError) as exc_info:
            await mw.wrap_model_call({}, handler)
        assert "星期五" in str(exc_info.value)
        assert "星期六" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_passes_on_conflict_fail_open(self):
        async def handler(req):
            return {"content": "明天是 2026年7月11日 星期五"}

        mw = FactCheckMiddleware(fail_strategy="open")
        result = await mw.wrap_model_call({}, handler)
        assert "星期五" in result["content"]
        assert result.get("_fact_check_warnings")

    @pytest.mark.asyncio
    async def test_math_error_caught(self):
        async def handler(req):
            return {"content": "23 + 32 = 100"}  # wrong

        mw = FactCheckMiddleware(fail_strategy="closed")
        with pytest.raises(FactCheckError):
            await mw.wrap_model_call({}, handler)

    @pytest.mark.asyncio
    async def test_exchange_rate_skipped_on_api_failure(self, monkeypatch):
        from nexus.backend.fact_check import exchange_rate as _exchange_rate

        monkeypatch.setattr(_exchange_rate, "fetch_rate", lambda f, t, api_key=None: None)

        async def handler(req):
            return {"content": "100 USD = 9999 CNY"}  # wrong but API down

        mw = FactCheckMiddleware(fail_strategy="closed")
        result = await mw.wrap_model_call({}, handler)
        assert "9999" in result["content"]  # passes through on skipped
