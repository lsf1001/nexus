"""fact_check 统一入口 verify() + 加权算法 测试。

WHY: spec §3.4 规定统一入口接受多 verifier,加权归一化算最终 score。
本测试锁 5 个性质: 单 verifier / 多 verifier 加权 / 1-N 失败归一化 /
全失败 0.0 / TimeoutError 计入失败。

stub verifier 签名严格对齐 4 个内置 verifier:
  ``async def verify(self, claim, context=None) -> VerificationResult``
``verify()`` 通过 ``_result_to_score`` 把 ``VerificationResult.verdict`` 映射
成分数("ok"→1.0, 其他→0.0)。
"""

from __future__ import annotations

from typing import Any

import pytest

from nexus.backend.fact_check.extractors import FactClaim
from nexus.backend.fact_check.verifiers import VerificationResult


def _stub_result(verdict: str = "ok") -> VerificationResult:
    """生成一个最小可用的 VerificationResult(claim 字段随便填,verdict 才是关键)。"""
    return VerificationResult(
        claim=FactClaim(raw_text="stub", kind="stub"),
        verdict=verdict,  # type: ignore[arg-type]
    )


class _StubOK:
    """总是返回 verdict="ok" 的 verifier(对应 score=1.0)。"""

    name = "stub_ok"
    weight = 1.0

    async def verify(self, claim: Any, context: dict | None = None) -> VerificationResult:
        """统一入口契约: 接受 claim + 可选 context,返回 VerificationResult。"""
        return _stub_result("ok")


class _StubFail:
    """总是抛 VerifierError 的 verifier。"""

    name = "stub_fail"
    weight = 1.0

    async def verify(self, claim: Any, context: dict | None = None) -> VerificationResult:
        from nexus.backend.fact_check.errors import VerifierError

        raise VerifierError("intentional failure")


class _StubTimeout:
    """总是抛 TimeoutError 的 verifier。"""

    name = "stub_timeout"
    weight = 1.0

    async def verify(self, claim: Any, context: dict | None = None) -> VerificationResult:
        raise TimeoutError()


@pytest.mark.asyncio
async def test_single_verifier_returns_its_score() -> None:
    """单 verifier "ok" → score=1.0。"""
    from nexus.backend.fact_check import verify

    result = await verify("claim1", verifiers=[_StubOK()])
    assert result.score == pytest.approx(1.0)
    assert result.claims_verified == 1
    assert result.claims_failed == 0


@pytest.mark.asyncio
async def test_weighted_average_across_verifiers() -> None:
    """多 verifier 加权: 2 个 ok 的 verifier,加权得 (1.0*1.0 + 1.0*2.0) / 3.0 = 1.0。

    StubOK + StubHeavy 都返回 verdict="ok" → score 都 1.0,加权归一化后 1.0。
    """
    from nexus.backend.fact_check import verify

    class StubHeavy:
        name = "stub_heavy"
        weight = 2.0

        async def verify(self, claim: Any, context: dict | None = None) -> VerificationResult:
            return _stub_result("ok")

    result = await verify("claim1", verifiers=[_StubOK(), StubHeavy()])
    assert result.score == pytest.approx((1.0 * 1.0 + 1.0 * 2.0) / 3.0)


@pytest.mark.asyncio
async def test_normalize_when_some_fail() -> None:
    """1 个 verifier 失败 → 跳过,剩余归一化。"""
    from nexus.backend.fact_check import verify

    # stub_fail 失败, 只剩 stub_ok 成功 → 1.0
    result = await verify("claim1", verifiers=[_StubOK(), _StubFail()])
    assert result.score == pytest.approx(1.0)
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
    # stub_timeout 失败, stub_ok 成功 → 1.0
    assert result.score == pytest.approx(1.0)
    assert result.claims_failed == 1


@pytest.mark.asyncio
async def test_default_verifiers_with_real_claim() -> None:
    """默认 ``_DEFAULT_VERIFIERS`` 路径真实走一遍(Fix 2 后必须能跑)。

    WHY: 之前 5 个加权测试都用 stub,从不触达 ``_DEFAULT_VERIFIERS``;
    真实 verifier 签名是 ``verify(claim, context) -> VerificationResult``,
    与 ``verify()`` 期望的契约一致后才不会抛 AttributeError。
    本测试喂一条带星期的事实声明,DateWeekday extractor 应能抽到 FactClaim,
    DateWeekdayVerifier 验证 weekday 一致 → score=1.0。
    """
    from nexus.backend.fact_check import verify

    # "2026年7月11日 星期六" → DateWeekdayExtractor 抽到 FactClaim →
    # DateWeekdayVerifier 验证通过 → verdict="ok" → score=1.0。
    # (2026-07-11 是星期六)
    result = await verify("明天是 2026年7月11日 星期六")
    assert 0.0 <= result.score <= 1.0
    assert result.claims_verified >= 1, (
        f"默认路径应至少验证 1 个 claim,实际 {result.claims_verified}; score={result.score}, reasons={result.reasons}"
    )
    assert result.score == pytest.approx(1.0)
