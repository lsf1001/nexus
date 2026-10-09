"""Deterministic fact-check pipeline + 统一 verify() 入口。

设计:
  - ``FactCheckPipeline.check(text)`` -- 历史入口,按 claim kind 选 verifier
    返回 ``FactCheckReport``,已有调用方(middleware / langchain_tools /
    mcp.fact_verify)继续走这条路径。
  - ``verify(claim, *, context, verifiers)`` -- 新统一入口(spec §3.4),
    接受多 verifier,加权归一化算最终 score;单 verifier 失败仅记
    ``logger.debug`` 跳过,不阻断主流程。
  - 4 个内置 verifier 注册到 ``_DEFAULT_VERIFIERS``,供 ``verify`` 默认调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nexus.backend.fact_check.errors import VerifierError
from nexus.backend.fact_check.pipeline import FactCheckPipeline, FactCheckReport, VerificationResult
from nexus.backend.fact_check.verifiers import (
    DateWeekdayVerifier,
    ExchangeRateVerifier,
    MathVerifier,
    UnitsVerifier,
)

logger = logging.getLogger(__name__)


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
class VerifyResult:
    """统一入口 ``verify()`` 的返回结果(spec §3.4)。

    Attributes:
        score: 0.0-1.0;多个 verifier 加权归一化后的最终分;全失败时为 0.0。
        claims_verified: 成功返回 score 的 verifier 个数。
        claims_failed: 抛 VerifierError / TimeoutError 的 verifier 个数。
        reasons: 标注本次结果状态(如全失败时 ``("all_verifiers_failed",)``)。
    """

    score: float
    claims_verified: int = 0
    claims_failed: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)


async def verify(
    claim: str,
    *,
    context: dict[str, Any] | None = None,
    verifiers: list[Any] | None = None,
) -> VerifyResult:
    """统一入口:遍历所有 verifier,加权计算最终 score(spec §3.4)。

    Args:
        claim: 待校验声明(字符串;verifier 可在子类层面决定如何解析)。
        context: 可选上下文(MCP 状态 / DB 状态 / session_id 等)。
        verifiers: 显式传入 verifier 列表;不传则用 4 个内置默认 verifier。
            每个 verifier 需有 ``name: str`` + ``weight: float`` 类属性 +
            ``async def verify(claim, context) -> float`` 方法。

    Returns:
        ``VerifyResult``。

    行为约定(spec §2.4):
      - 单 verifier 抛 ``VerifierError`` / ``asyncio.TimeoutError`` →
        静默跳过 + ``logger.debug``,剩余 verifier 权重归一化后再加权
      - 全部 verifier 失败 → score=0.0, reasons=("all_verifiers_failed",)
      - 不抛异常到调用方
    """
    vs = verifiers if verifiers is not None else list(_DEFAULT_VERIFIERS)
    weighted_sum = 0.0
    total_weight = 0.0
    claims_verified = 0
    claims_failed = 0

    for v in vs:
        try:
            score = await v.verify(claim, context)
            weighted_sum += v.weight * score
            total_weight += v.weight
            claims_verified += 1
        except (TimeoutError, VerifierError) as e:
            logger.debug(
                "verifier %s failed: %s",
                getattr(v, "name", type(v).__name__),
                e,
            )
            claims_failed += 1
            continue

    if total_weight == 0.0:
        return VerifyResult(
            score=0.0,
            claims_verified=0,
            claims_failed=claims_failed,
            reasons=("all_verifiers_failed",),
        )

    return VerifyResult(
        score=weighted_sum / total_weight,
        claims_verified=claims_verified,
        claims_failed=claims_failed,
    )


__all__ = [
    "FactCheckPipeline",
    "FactCheckReport",
    "VerificationResult",
    "VerifyResult",
    "verify",
]
