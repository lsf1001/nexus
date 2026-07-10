"""Orchestrates extract → verify → report."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus.backend.fact_check.extractors import (
    DateWeekdayExtractor,
    ExchangeRateExtractor,
    FactClaim,
    MathExtractor,
    UnitsExtractor,
)
from nexus.backend.fact_check.verifiers import (
    DateWeekdayVerifier,
    ExchangeRateVerifier,
    MathVerifier,
    UnitsVerifier,
    VerificationResult,
)


@dataclass
class FactCheckReport:
    """单次 fact-check 的汇总结果。"""

    text: str
    claims_total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    conflicts: list[VerificationResult] = field(default_factory=list)
    all_results: list[VerificationResult] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        """是否存在冲突。"""
        return len(self.conflicts) > 0

    def to_dict(self) -> dict:
        """序列化为 dict（用于落库 / 日志）。"""
        return {
            "claims_total": self.claims_total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "conflicts": [
                {
                    "claim_text": r.claim.raw_text,
                    "kind": r.claim.kind,
                    "verdict": r.verdict,
                    "claimed": r.claimed_weekday_zh or r.expected_value,
                    "actual": r.actual_weekday_zh or r.actual_value,
                }
                for r in self.conflicts
            ],
        }


_EXTRACTORS: dict[str, object] = {
    "date_weekday": DateWeekdayExtractor(),
    "math": MathExtractor(),
    "unit": UnitsExtractor(),
    "exchange_rate": ExchangeRateExtractor(),
}

_VERIFIERS: dict[str, object] = {
    "date_weekday": DateWeekdayVerifier(),
    "math": MathVerifier(),
    "unit": UnitsVerifier(),
    "exchange_rate": ExchangeRateVerifier(),
}


class FactCheckPipeline:
    """对文本运行所有启用的 extractor + verifier，返回 FactCheckReport。

    Args:
        config: 可选配置，键 ``enabled_claim_types`` 是要启用的 claim 类型列表。
    """

    DEFAULT_ENABLED: list[str] = ["date_weekday", "math", "unit", "exchange_rate"]

    def __init__(self, config: dict | None = None) -> None:
        self.enabled: list[str] = (config or {}).get("enabled_claim_types", self.DEFAULT_ENABLED)

    def check(self, text: str, api_key: str | None = None) -> FactCheckReport:
        """对 text 跑所有启用的 claim 检查。

        Args:
            text: 待校验文本
            api_key: 可选汇率 API key

        Returns:
            FactCheckReport
        """
        report = FactCheckReport(text=text)
        for kind in self.enabled:
            extractor = _EXTRACTORS.get(kind)
            verifier = _VERIFIERS.get(kind)
            if not extractor or not verifier:
                continue
            claims: list[FactClaim] = extractor.extract(text)  # type: ignore[attr-defined]
            for claim in claims:
                report.claims_total += 1
                if kind == "exchange_rate":
                    result = verifier.verify(claim, api_key=api_key)  # type: ignore[attr-defined]
                else:
                    result = verifier.verify(claim)  # type: ignore[attr-defined]
                report.all_results.append(result)
                if result.verdict == "ok":
                    report.passed += 1
                elif result.verdict == "conflict":
                    report.failed += 1
                    report.conflicts.append(result)
                elif result.verdict == "error":
                    report.errors += 1
                else:  # skipped
                    report.skipped += 1
        return report
