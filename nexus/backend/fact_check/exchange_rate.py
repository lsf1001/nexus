"""Exchange rate fetcher with 1-hour in-memory cache.

Uses https://api.exchangerate-api.com/v4/latest/{base} (free, no auth).
On API failure, returns None (fail-open in verifier).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

_CACHE: dict[str, CachedRate] = {}


@dataclass
class CachedRate:
    """缓存的汇率条目。"""

    rate: float
    fetched_at: float


class ExchangeRateCache:
    """带 TTL 的内存缓存。"""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        """初始化缓存。默认 TTL 为 1 小时。"""
        self.ttl = ttl_seconds

    def get(self, base: str) -> float | None:
        """获取缓存汇率；过期或不存在返回 None。"""
        entry = _CACHE.get(base)
        if entry is None:
            return None
        if time.time() - entry.fetched_at > self.ttl:
            return None
        return entry.rate

    def set(self, base: str, payload: dict) -> None:
        """写入缓存。payload 需含 'rate' 字段。"""
        if "rate" in payload:
            _CACHE[base] = CachedRate(
                rate=float(payload["rate"]),
                fetched_at=payload.get("fetched_at", time.time()),
            )


def clear_cache() -> None:
    """清空缓存（测试用）。"""
    _CACHE.clear()


async def _fetch_api(url: str) -> dict:
    """通过 HTTP 拉取汇率 JSON。测试可通过 monkeypatch 替换。"""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return await resp.json()


def fetch_rate(from_ccy: str, to_ccy: str, api_key: str | None = None) -> float | None:
    """同步获取汇率：先查缓存，缓存未命中再调 API。失败返回 None。

    Args:
        from_ccy: 源币种代码（3 字母，如 USD）
        to_ccy: 目标币种代码（如 CNY）
        api_key: 可选 API key（当前实现忽略，免费 API 不用）

    Returns:
        汇率（float），失败时 None。
    """
    if from_ccy == to_ccy:
        return 1.0

    cache = ExchangeRateCache()
    cached = cache.get(from_ccy)
    if cached is not None:
        return cached

    # 缓存未命中，调 API
    try:
        data = asyncio.run(_fetch_api(f"https://api.exchangerate-api.com/v4/latest/{from_ccy}"))
        rates = data.get("rates", {})
        if to_ccy not in rates:
            return None
        rate = float(rates[to_ccy])
        cache.set(from_ccy, {"rate": rate, "fetched_at": time.time()})
        return rate
    except Exception:
        return None
