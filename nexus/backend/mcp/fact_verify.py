"""fact_verify MCP server — 把 FactCheckPipeline 暴露给 LLM 工具调用。

设计目标:
- LLM 在输出前可主动调 verify_claims() 自检声明
- 包装 FactCheckPipeline,返回形状适配 MCP 工具(JSON-friendly)
- 纯函数 + 模块级懒初始化 pipeline 实例
- 时区继承 FactCheckMiddleware 的 Asia/Shanghai

工具:
- verify_claims(text: str) -> FactVerifyResult
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from nexus.backend.fact_check import FactCheckPipeline


@dataclass(frozen=True)
class FactVerifyResult:
    """verify_claims 返回类型,MCP 序列化友好。"""

    ok: bool
    claims_total: int
    conflicts_total: int
    claims: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PIPELINE: FactCheckPipeline | None = None


def _get_pipeline() -> FactCheckPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = FactCheckPipeline()
    return _PIPELINE


def _conflict_summary(result: Any) -> dict[str, Any]:
    """从 VerificationResult 抽取 JSON 友好摘要(claim_text/kind/expected/actual/reason)。"""
    claim = getattr(result, "claim", None)
    return {
        "claim_text": getattr(claim, "raw_text", str(claim)),
        "kind": getattr(claim, "kind", "unknown"),
        "verdict": getattr(result, "verdict", "unknown"),
        "expected": getattr(result, "expected_value", None) or getattr(result, "claimed_weekday_zh", None),
        "actual": getattr(result, "actual_value", None) or getattr(result, "actual_weekday_zh", None),
    }


def verify_claims(text: str) -> FactVerifyResult:
    """对 text 跑 FactCheckPipeline,返回结构化结果。

    Args:
        text: LLM 拟发出的回复文本

    Returns:
        FactVerifyResult: ok / claims / conflicts 三核心字段
    """
    report = _get_pipeline().check(text)
    conflicts = [_conflict_summary(r) for r in report.conflicts]
    all_results = getattr(report, "all_results", [])
    claims = [_conflict_summary(r) for r in all_results]
    return FactVerifyResult(
        ok=not report.has_conflict,
        claims_total=report.claims_total,
        conflicts_total=len(conflicts),
        claims=claims,
        conflicts=conflicts,
    )
