"""Deterministic fact-check pipeline + 统一 verify() 入口。

设计:
  - ``FactCheckPipeline.check(text)`` -- 历史入口,按 claim kind 选 verifier
    返回 ``FactCheckReport``,已有调用方(middleware / langchain_tools /
    mcp.fact_verify)继续走这条路径。
  - ``verify(claim, *, context, verifiers)`` -- 新统一入口(spec §3.4),
    接受多 verifier,加权归一化算最终 score;单 verifier 失败仅记
    ``logger.debug`` 跳过,不阻断主流程。
  - 4 个内置 verifier 注册到 ``_DEFAULT_VERIFIERS``,供 ``verify`` 默认调用。

verify() 内部流程(spec §3.4 + plan §6.6):
  1. 把 ``claim`` 字符串经过 4 个内置 extractor 抽取成 ``FactClaim`` 列表。
     若 caller 显式传 ``verifiers=[...]``(e.g. 自定义 stub),则**跳过提取**
     直接把字符串喂给每个 verifier(stub 自己负责解释 claim)。
  2. 对每个 FactClaim × 默认 verifier 组合,按 ``claim.kind`` 路由;
     不匹配 kind 的 verifier 返回 ``verdict="skipped"`` 不计贡献。
  3. 把 ``VerificationResult.verdict`` 直接分流:"ok" 计加权,
     "conflict" 仅计数,"skipped" 不计贡献。
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

from nexus.backend.fact_check.errors import VerifierError
from nexus.backend.fact_check.extractors import (
    DateWeekdayExtractor,
    ExchangeRateExtractor,
    FactClaim,
    MathExtractor,
    UnitsExtractor,
)
from nexus.backend.fact_check.pipeline import FactCheckPipeline, FactCheckReport, VerificationResult
from nexus.backend.fact_check.verifiers import (
    DateWeekdayVerifier,
    ExchangeRateVerifier,
    MathVerifier,
    UnitsVerifier,
)

logger = logging.getLogger(__name__)


# 4 个内置 extractor,负责从字符串里抽取 FactClaim。
_EXTRACTORS: dict[str, Any] = {
    "date_weekday": DateWeekdayExtractor(),
    "math": MathExtractor(),
    "unit": UnitsExtractor(),
    "exchange_rate": ExchangeRateExtractor(),
}


# 4 个内置 verifier(单例),默认 verify() 时遍历。spec §3.4 + plan §6.3:
#   - Math:         weight=1.5 (AST 求值,置信度最高)
#   - DateWeekday:  weight=1.0 (datetime 算 weekday,确定性强)
#   - Units:        weight=1.0 (单位换算,确定性强)
#   - ExchangeRate: weight=0.5 (汇率 API 波动大,置信度低)
_DEFAULT_VERIFIERS: tuple[Any, ...] = (
    DateWeekdayVerifier(),
    MathVerifier(),
    UnitsVerifier(),
    ExchangeRateVerifier(),
)


@dataclass(frozen=True)
class _ScoreOutcome:
    """单 verifier 跑一次的中间结果。

    Attributes:
        verdict: ``"ok"`` / ``"conflict"`` / ``"skipped"``。
        weight: 该 verifier 的权重,仅 ``"ok"`` 时累加。
    """

    verdict: str
    weight: float


@dataclass(frozen=True)
class _AggregateOutcome:
    """遍历所有 (claim × verifier) 组合后的累计统计。

    Attributes:
        weighted_sum: 所有 ``verdict="ok"`` 的 ``weight * 1.0`` 之和。
        total_weight: 所有 ``verdict="ok"`` 的权重之和(归一化分母)。
        verified: ``verdict="ok"`` 的 verifier 个数。
        failed: 抛 ``TimeoutError`` / ``VerifierError`` 的 verifier 个数。
        conflicted: ``verdict="conflict"`` 的 verifier 个数。
    """

    weighted_sum: float
    total_weight: float
    verified: int
    failed: int
    conflicted: int


@dataclass(frozen=True)
class VerifyResult:
    """统一入口 ``verify()`` 的返回结果(spec §3.4)。

    Attributes:
        score: 0.0-1.0;多个 verifier 加权归一化后的最终分;全失败时为 0.0。
        claims_verified: 通过校验的 verifier 个数(verdict="ok")。
        claims_failed: 抛 VerifierError / TimeoutError 的 verifier 个数。
        claims_conflicted: 返回 verdict="conflict" 的 verifier 个数。
        reasons: 标注本次结果状态(如全失败时 ``("all_verifiers_failed",)``)。
    """

    score: float
    claims_verified: int = 0
    claims_failed: int = 0
    claims_conflicted: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _extract_claims(text: str) -> list[FactClaim]:
    """用 4 个内置 extractor 从文本里抽 FactClaim 列表;按 kind 去重。

    Args:
        text: 原始字符串。

    Returns:
        抽取到的 FactClaim 列表;不抛异常,内部 regex 不匹配时返回空列表。
    """
    out: list[FactClaim] = []
    for ex in _EXTRACTORS.values():
        try:
            out.extend(ex.extract(text))
        except (AttributeError, ValueError) as e:
            logger.debug("extractor %s failed: %s", type(ex).__name__, e)
    return out


async def _score_one_verifier(
    v: Any,
    claim: Any,
    context: dict[str, Any] | None,
) -> _ScoreOutcome:
    """单 verifier 跑一次,返回 ``(verdict, weight)``;异常留给 caller 处理。

    同步 / 异步 verifier 都吃:``v.verify`` 同步返回 ``VerificationResult``
    时直接用;返回 awaitable 时 await(内置 4 个 verifier 都是 async,但
    测试 stub 也可能给 sync)。
    """
    result = v.verify(claim, context)
    if inspect.isawaitable(result):
        result = await result  # type: ignore[assignment]
    return _ScoreOutcome(verdict=result.verdict, weight=v.weight)  # type: ignore[union-attr]


async def _aggregate_results(
    claims: list[Any],
    vs: list[Any],
    context: dict[str, Any] | None,
) -> _AggregateOutcome:
    """遍历所有 (claim × verifier) 组合,返回累计统计。

    单 verifier 抛 ``VerifierError`` / ``TimeoutError`` 仅 ``logger.debug``
    + 计入 ``failed``,不阻断主流程(spec §2.4)。
    """
    weighted_sum = 0.0
    total_weight = 0.0
    verified = 0
    failed = 0
    conflicted = 0
    for c in claims:
        for v in vs:
            try:
                outcome = await _score_one_verifier(v, c, context)
            except (TimeoutError, VerifierError) as exc:
                logger.debug(
                    "verifier %s failed: %s",
                    getattr(v, "name", type(v).__name__),
                    exc,
                )
                failed += 1
                continue
            if outcome.verdict == "ok":
                weighted_sum += outcome.weight
                total_weight += outcome.weight
                verified += 1
            elif outcome.verdict == "conflict":
                conflicted += 1
            # "skipped" 不计入任何累计(spec §3.4)
    return _AggregateOutcome(
        weighted_sum=weighted_sum,
        total_weight=total_weight,
        verified=verified,
        failed=failed,
        conflicted=conflicted,
    )


async def verify(
    claim: str,
    *,
    context: dict[str, Any] | None = None,
    verifiers: list[Any] | None = None,
) -> VerifyResult:
    """编排:抽取声明 → 聚合打分 → 输出 ``VerifyResult``(spec §3.4)。

    三段式(每段一个 helper):
      1. ``claims`` 抽取(默认走 4 个 extractor;显式 ``verifiers`` 时跳过)
      2. ``_aggregate_results`` 跑加权聚合
      3. 本函数末尾把聚合结果映射成 ``VerifyResult``
    """
    vs = list(_DEFAULT_VERIFIERS) if verifiers is None else list(verifiers)
    claims = _extract_claims(claim) if verifiers is None else [claim]  # type: ignore[list-item]
    agg = await _aggregate_results(claims, vs, context)
    if agg.total_weight == 0.0:
        return VerifyResult(
            score=0.0,
            claims_verified=0,
            claims_failed=agg.failed,
            claims_conflicted=agg.conflicted,
            reasons=("all_verifiers_failed",),
        )
    return VerifyResult(
        score=agg.weighted_sum / agg.total_weight,
        claims_verified=agg.verified,
        claims_failed=agg.failed,
        claims_conflicted=agg.conflicted,
    )


__all__ = [
    "FactCheckPipeline",
    "FactCheckReport",
    "VerificationResult",
    "VerifyResult",
    "verify",
]
