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
  3. 用 ``_result_to_score`` 把 ``VerificationResult.verdict`` 映射到
     0.0-1.0,加权归一化。
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


def _result_to_score(result: VerificationResult) -> float:
    """把 ``VerificationResult.verdict`` 映射到 0.0-1.0 浮点分,供 ``verify()`` 加权用。

    映射规则:
      - ``verdict="ok"`` → 1.0(声明通过校验)
      - ``verdict="conflict"`` → 0.0(声明与事实不符)
      - ``verdict="skipped"`` → 0.0(此 verifier 不适用本声明,不计贡献)
      - ``verdict="error"`` → 0.0(校验过程异常,等同失败)

    Args:
        result: 单个 verifier 的 ``VerificationResult`` 输出。

    Returns:
        0.0-1.0 浮点分;只有 ``"ok"`` 给 1.0,其余情形视为 0。
    """
    return 1.0 if result.verdict == "ok" else 0.0


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


async def verify(
    claim: str,
    *,
    context: dict[str, Any] | None = None,
    verifiers: list[Any] | None = None,
) -> VerifyResult:
    """统一入口:遍历所有 verifier,加权计算最终 score(spec §3.4)。

    Args:
        claim: 待校验声明文本;走默认路径时会先经 extractor 抽取 FactClaim。
        context: 可选上下文(MCP 状态 / DB 状态 / session_id 等)。
        verifiers: 显式传入 verifier 列表;不传则用 4 个内置默认 verifier。
            每个 verifier 需有 ``name: str`` + ``weight: float`` 类属性 +
            ``async def verify(claim, context) -> VerificationResult`` 方法。
            **当显式传 ``verifiers`` 时,跳过 extractor,直接喂字符串**(stub
            风格;测试用)。

    Returns:
        ``VerifyResult``。

    行为约定(spec §2.4):
      - 单 verifier 抛 ``VerifierError`` / ``asyncio.TimeoutError`` →
        静默跳过 + ``logger.debug``,剩余 verifier 权重归一化后再加权
      - 全部 verifier 失败 → score=0.0, reasons=("all_verifiers_failed",)
      - 不抛异常到调用方
    """
    use_defaults = verifiers is None
    vs = list(_DEFAULT_VERIFIERS) if use_defaults else list(verifiers)

    # 默认路径:先用 extractor 抽声明,再逐条 × verifier 路由。
    # 显式路径(stub):直接喂字符串给每个 verifier。
    if use_defaults:
        claims = _extract_claims(claim)
    else:
        claims = [claim]  # type: ignore[list-item]

    weighted_sum = 0.0
    total_weight = 0.0
    claims_verified = 0
    claims_failed = 0
    claims_conflicts = 0

    for c in claims:
        for v in vs:
            try:
                result = v.verify(c, context)
                if inspect.isawaitable(result):
                    result = await result
                score = _result_to_score(result)  # type: ignore[arg-type]
                verdict = result.verdict  # type: ignore[attr-defined]
                if verdict == "skipped":
                    continue
                if verdict == "conflict":
                    claims_conflicts += 1
                else:  # "ok"
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
            claims_conflicted=claims_conflicts,
            reasons=("all_verifiers_failed",),
        )

    return VerifyResult(
        score=weighted_sum / total_weight,
        claims_verified=claims_verified,
        claims_failed=claims_failed,
        claims_conflicted=claims_conflicts,
    )


__all__ = [
    "FactCheckPipeline",
    "FactCheckReport",
    "VerificationResult",
    "VerifyResult",
    "verify",
]
