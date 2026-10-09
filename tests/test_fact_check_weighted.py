"""fact_check 统一入口 verify() + 加权算法 测试。

WHY: spec §3.4 规定统一入口接受多 verifier,加权归一化算最终 score。
本测试锁 5 个性质: 单 verifier / 多 verifier 加权 / 1-N 失败归一化 /
全失败 0.0 / TimeoutError 计入失败。
"""

from __future__ import annotations

from typing import Any

import pytest


class _StubOK:
    """总是返回 0.8 的 verifier(统一入口的接口契约)。"""

    name = "stub_ok"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        """统一入口契约: 接受 claim + 可选 context,返回 0.0-1.0 score。"""
        return 0.8


class _StubPartial:
    """返回 0.6 的 verifier。"""

    name = "stub_partial"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        return 0.6


class _StubFail:
    """总是抛 VerifierError 的 verifier。"""

    name = "stub_fail"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        from nexus.backend.fact_check.errors import VerifierError

        raise VerifierError("intentional failure")


class _StubTimeout:
    """总是抛 TimeoutError 的 verifier。"""

    name = "stub_timeout"
    weight = 1.0

    async def verify(self, claim: Any, context: Any | None = None) -> float:
        raise TimeoutError()


@pytest.mark.asyncio
async def test_single_verifier_returns_its_score() -> None:
    """单 verifier → 直接返回该 score。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubOK()])
    assert result.score == pytest.approx(0.8)
    assert result.claims_verified == 1
    assert result.claims_failed == 0


@pytest.mark.asyncio
async def test_weighted_average_across_verifiers() -> None:
    """多 verifier 加权: (0.8*1.0 + 0.6*2.0) / (1.0+2.0) = 2.0/3.0。"""
    from nexus.backend.fact_check import verify

    class StubHeavy:
        name = "stub_heavy"
        weight = 2.0

        async def verify(self, claim: Any, context: Any | None = None) -> float:
            return 0.6

    result = await verify("claim1", verifiers=[_StubOK(), StubHeavy()])
    assert result.score == pytest.approx((0.8 * 1.0 + 0.6 * 2.0) / 3.0)


@pytest.mark.asyncio
async def test_normalize_when_some_fail() -> None:
    """1 个 verifier 失败 → 跳过,剩余归一化。"""
    from nexus.backend.fact_check import verify

    # stub_fail 失败, 只剩 stub_ok 成功 → 0.8
    result = await verify("claim1", verifiers=[_StubOK(), _StubFail()])
    assert result.score == pytest.approx(0.8)
    assert result.claims_verified == 1
    assert result.claims_failed == 1


@pytest.mark.asyncio
async def test_all_failed_returns_zero() -> None:
    """全部 verifier 失败 → score=0.0, reasons=("all_verifiers_failed",)。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubFail(), _StubTimeout()])
    assert result.score == 0.0
    assert "all_verifiers_failed" in result.reasons


@pytest.mark.asyncio
async def test_timeout_error_counts_as_failure() -> None:
    """asyncio.TimeoutError 计入失败(不抛到外层)。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubTimeout(), _StubOK()])
    # stub_timeout 失败, stub_ok 成功 → 0.8
    assert result.score == pytest.approx(0.8)
    assert result.claims_failed == 1
