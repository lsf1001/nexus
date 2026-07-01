"""HITL confirmation 路径 aget_state 1s TTL 缓存回归测试。

WHY 存在:audit 2026-07-01 发现 confirmation_response 高频重复调
``agent.aget_state`` 读 checkpoint(每次走 SQLite hit)。同 session 在
用户决策窗口(< 1s)内连续读应该复用 cache,不同 session 必须重读,
HITL 完成后必须 invalidate。
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试前后清缓存,避免相互污染。"""
    from nexus.backend.api.ws import handlers as h

    if hasattr(h, "_interrupts_cache"):
        h._interrupts_cache.clear()
    yield
    if hasattr(h, "_interrupts_cache"):
        h._interrupts_cache.clear()


@pytest.mark.asyncio
async def test_same_session_caches_within_ttl(monkeypatch):
    """同 session 第二次调用 < 1s 必须命中缓存,不再调 aget_state。"""
    from nexus.backend.api.ws import handlers as h

    fetch_count = {"n": 0}

    class _StubSnapshot:
        def __init__(self, intr):
            self.interrupts = intr

    class _StubAgent:
        async def aget_state(self, cfg):
            fetch_count["n"] += 1
            return _StubSnapshot([{"id": "1", "value": "x"}])

    monkeypatch.setattr(h, "get_agent", lambda: _StubAgent())

    # 第一次 cache miss → 调 aget_state
    r1 = await h._resolve_pending_interrupts("sess-A")
    # 第二次 cache hit → 不调
    r2 = await h._resolve_pending_interrupts("sess-A")
    # 第三次仍 hit
    r3 = await h._resolve_pending_interrupts("sess-A")

    assert fetch_count["n"] == 1, "同 session < 1s 重复调用应命中缓存"
    assert r1.interrupts == r2.interrupts == r3.interrupts


@pytest.mark.asyncio
async def test_different_session_does_not_share_cache(monkeypatch):
    """不同 session_id 是独立缓存 key,必须各自走 aget_state。"""
    from nexus.backend.api.ws import handlers as h

    fetch_count = {"n": 0}

    class _StubSnapshot:
        interrupts = [{"id": "1"}]

    class _StubAgent:
        async def aget_state(self, cfg):
            fetch_count["n"] += 1
            return _StubSnapshot()

    monkeypatch.setattr(h, "get_agent", lambda: _StubAgent())

    await h._resolve_pending_interrupts("sess-A")
    await h._resolve_pending_interrupts("sess-A")  # cache hit
    await h._resolve_pending_interrupts("sess-B")  # cache miss → 重读

    assert fetch_count["n"] == 2


@pytest.mark.asyncio
async def test_cache_invalidated_by_invalidate_call(monkeypatch):
    """显式 _invalidate_interrupts_cache 后,下一次必须重读。"""
    from nexus.backend.api.ws import handlers as h

    fetch_count = {"n": 0}

    class _StubSnapshot:
        def __init__(self, intr):
            self.interrupts = intr

    class _StubAgent:
        async def aget_state(self, cfg):
            fetch_count["n"] += 1
            return _StubSnapshot([{"id": "1"}])

    monkeypatch.setattr(h, "get_agent", lambda: _StubAgent())

    await h._resolve_pending_interrupts("sess-A")  # miss → 1
    await h._resolve_pending_interrupts("sess-A")  # hit
    h._invalidate_interrupts_cache("sess-A")
    await h._resolve_pending_interrupts("sess-A")  # miss → 2

    assert fetch_count["n"] == 2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch):
    """超过 TTL(1s)后,缓存失效,下一次重读。"""
    from nexus.backend.api.ws import handlers as h

    fetch_count = {"n": 0}

    class _StubSnapshot:
        def __init__(self, intr):
            self.interrupts = intr

    class _StubAgent:
        async def aget_state(self, cfg):
            fetch_count["n"] += 1
            return _StubSnapshot([{"id": "1"}])

    monkeypatch.setattr(h, "get_agent", lambda: _StubAgent())

    # 用 monkeypatch 把 _INTERRUPTS_CACHE_TTL_SECONDS 改成 0.1,避免真实 sleep 1s
    monkeypatch.setattr(h, "_INTERRUPTS_CACHE_TTL_SECONDS", 0.1)

    await h._resolve_pending_interrupts("sess-A")  # miss → 1
    await h._resolve_pending_interrupts("sess-A")  # hit
    time.sleep(0.15)  # 超过 0.1s TTL
    await h._resolve_pending_interrupts("sess-A")  # miss → 2 (TTL expired)

    assert fetch_count["n"] == 2


@pytest.mark.asyncio
async def test_aget_state_failure_returns_empty_tuple_and_does_not_cache(monkeypatch):
    """aget_state 抛异常时返回空 tuple,且**不**写入缓存(下次还要重试)。

    WHY 不缓存:失败可能是 transient(网络/锁等待),缓存失败结果会让后续
    confirmation_response 一直返回空,即使实际 state 已恢复。
    """
    from nexus.backend.api.ws import handlers as h

    fetch_count = {"n": 0}

    class _FailingAgent:
        async def aget_state(self, cfg):
            fetch_count["n"] += 1
            raise RuntimeError("transient")

    monkeypatch.setattr(h, "get_agent", lambda: _FailingAgent())

    r1 = await h._resolve_pending_interrupts("sess-A")  # fail → ()
    r2 = await h._resolve_pending_interrupts("sess-A")  # 失败不应缓存 → 重试

    assert r1.interrupts == ()
    assert r2.interrupts == ()
    # 失败结果不缓存,所以两次都重试
    assert fetch_count["n"] == 2


@pytest.mark.asyncio
async def test_invalidate_nonexistent_session_is_noop(monkeypatch):
    """_invalidate_interrupts_cache 对不存在 session 静默 no-op(``.pop(default)``)。"""
    from nexus.backend.api.ws import handlers as h

    # 不应抛 KeyError
    h._invalidate_interrupts_cache("never-existed")
    # 也不应影响其他 session
    h._interrupts_cache["sess-A"] = (time.monotonic(), ())
    h._invalidate_interrupts_cache("sess-B")
    assert "sess-A" in h._interrupts_cache


@pytest.mark.asyncio
async def test_cache_status_reports_hit_miss_fail(monkeypatch):
    """``cache_status`` 字段精确反映 hit/miss/fail,handler 日志可直接用。"""
    from nexus.backend.api.ws import handlers as h

    class _Snapshot:
        def __init__(self, intr):
            self.interrupts = intr

    class _GoodAgent:
        async def aget_state(self, cfg):
            return _Snapshot([{"id": "1"}])

    class _FailAgent:
        async def aget_state(self, cfg):
            raise RuntimeError("boom")

    # miss → miss
    monkeypatch.setattr(h, "get_agent", lambda: _GoodAgent())
    r1 = await h._resolve_pending_interrupts("sess-X")
    assert r1.cache_status == "miss"

    # hit → hit
    r2 = await h._resolve_pending_interrupts("sess-X")
    assert r2.cache_status == "hit"

    # fail → fail (不写入缓存)
    monkeypatch.setattr(h, "get_agent", lambda: _FailAgent())
    h._invalidate_interrupts_cache("sess-X")
    r3 = await h._resolve_pending_interrupts("sess-X")
    assert r3.cache_status == "fail"
    assert r3.interrupts == ()

    # 失败不缓存 → 下次仍是 miss(非 hit)
    monkeypatch.setattr(h, "get_agent", lambda: _GoodAgent())
    r4 = await h._resolve_pending_interrupts("sess-X")
    assert r4.cache_status == "miss"  # 因为前一次是 fail,没缓存
