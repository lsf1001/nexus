"""工具结果自评：让 subagent 显式调用 ``tool_self_evaluate`` 评估工具结果质量。

本模块是 Phase 2 (Rubrics) Task 2.6 的实现——subagent 在调 ``web_search``
等工具拿到结果后，用 :class:`ToolSelfEvaluator` 评估结果是否充分；得分
低于阈值时 subagent 收到"搜索结果不充分"的反馈，可以重试或换工具。

设计要点：
  - **专用 tool_correctness 评估**：用 :data:`TOOL_CORRECTNESS_RUBRIC`
    单独评估，prompt 强调"评估工具返回结果的质量和相关性"。
  - **thumbs-up / thumbs-down**：根据 score 阈值返回 ``"ok"`` / ``"retry"``
    / ``"fallback"`` 三档决策，便于 subagent 决策。
  - **不污染主流程**：evaluator 自身异常被捕获，返回 fallback verdict
    ``"ok"``（宁可放过也不阻断 subagent 流程）。
  - **不依赖 deepagents 内部图**：以独立工具 + 类的方式提供，subagent
    的 system prompt 教它在使用 ``web_search`` 后调用 ``tool_self_evaluate``。
  - **不可变**（CLAUDE.md §11）：所有状态在构造时定。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from ..rubrics.judge import RubricJudge
from ..rubrics.schemas import (
    Score,
)

__all__ = ["ToolSelfEvaluator", "ToolEvaluation"]


logger = logging.getLogger(__name__)


# ==================== 数据类 ====================


@dataclass(frozen=True)
class ToolEvaluation:
    """工具自评结果。

    Attributes:
        verdict: 自评决策（``"ok"`` / ``"retry"`` / ``"fallback"``）。
        score: tool_correctness 维度的 0.0-1.0 评分。
        reasoning: 评分员解释（中文）。
        evidence: 评分员引用的关键句。
    """

    verdict: str
    score: float
    reasoning: str
    evidence: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """verdict == "ok" 的便捷判断。"""
        return self.verdict == "ok"

    @property
    def should_retry(self) -> bool:
        """verdict == "retry" 的便捷判断。"""
        return self.verdict == "retry"

    @property
    def should_fallback(self) -> bool:
        """verdict == "fallback" 的便捷判断。"""
        return self.verdict == "fallback"


# ==================== 主类 ====================


@dataclass(frozen=True)
class ToolSelfEvaluator:
    """工具结果自评器：给 subagent 调 ``web_search`` 等工具后做质量检查。

    Attributes:
        judge: 已构造的 :class:`RubricJudge`（用 tool_correctness 维度评估）。
        retry_threshold: 低于此分视为"结果不充分"，建议重试。
        fallback_threshold: 低于此分视为"完全不行"，建议切换 fallback 工具。
        retry_threshold 必须 >= fallback_threshold。
    """

    judge: RubricJudge
    retry_threshold: float = 0.6
    fallback_threshold: float = 0.3

    def __post_init__(self) -> None:
        """构造期校验阈值。"""
        if not (0.0 <= self.fallback_threshold <= self.retry_threshold <= 1.0):
            raise ValueError(
                f"阈值不合法：fallback={self.fallback_threshold} ≤ "
                f"retry={self.retry_threshold}，且都在 [0, 1]"
            )

    async def evaluate(
        self,
        tool_name: str,
        query: str,
        results: Sequence[str] | str,
    ) -> ToolEvaluation:
        """评估工具调用结果质量，返回 ``ToolEvaluation``。

        Args:
            tool_name: 工具名（如 ``"web_search"``）。
            query: 原始查询（用户问题或子查询）。
            results: 工具返回结果。可以是字符串列表（多条结果）或单字符串。

        Returns:
            :class:`ToolEvaluation`，含 verdict / score / reasoning。
            任何内部异常都被捕获，返回 verdict="ok" + 异常信息作 reasoning
            （不污染 subagent 主流程）。
        """
        # 把 results 归一化成字符串列表
        if isinstance(results, str):
            results_list: list[str] = [results]
        else:
            results_list = list(results)

        # 构造 tool_calls 形态喂给 RubricJudge
        tool_calls = [
            {
                "name": tool_name,
                "args": {"query": query},
                "result": "\n".join(results_list)[:500],
            }
        ]
        question = f"[subagent 工具调用] {tool_name} 查询：{query}"

        try:
            scores = await self.judge.judge(
                question=question,
                response="",  # subagent 评估的是工具结果，不是助手回复
                tool_calls=tool_calls,
            )
        except Exception as exc:  # noqa: BLE001 — 边界收口
            logger.warning("ToolSelfEvaluator 评估异常，降级为 ok: %s", exc)
            return ToolEvaluation(
                verdict="ok",
                score=1.0,
                reasoning=f"评估异常：{type(exc).__name__}: {exc}",
            )

        # 从 scores 里找 tool_correctness 维度
        tool_score = next(
            (s for s in scores if s.rubric_name == "tool_correctness"),
            scores[0] if scores else None,
        )
        if tool_score is None:
            return ToolEvaluation(
                verdict="ok",
                score=1.0,
                reasoning="无可用评分",
            )

        return self._decide(tool_score)

    def _decide(self, score: Score) -> ToolEvaluation:
        """根据 score 和阈值判定 verdict。"""
        if score.score < self.fallback_threshold:
            verdict = "fallback"
        elif score.score < self.retry_threshold:
            verdict = "retry"
        else:
            verdict = "ok"
        return ToolEvaluation(
            verdict=verdict,
            score=score.score,
            reasoning=score.reasoning,
            evidence=score.evidence,
        )


# ==================== LangChain 工具包装 ====================


def build_tool_self_eval_tool(evaluator: ToolSelfEvaluator):
    """把 ToolSelfEvaluator 包装成 LangChain Tool，注入到 subagent 工具列表。

    返回的工具名固定为 ``tool_self_evaluate``，subagent 的 system prompt
    教它"调用 web_search 后立即调 tool_self_evaluate"。

    Args:
        evaluator: 已构造的 :class:`ToolSelfEvaluator` 实例。

    Returns:
        LangChain ``BaseTool`` 实例，可直接 ``create_deep_agent(tools=[..., tool])``。
    """
    from langchain_core.tools import tool

    @tool
    async def tool_self_evaluate(
        tool_name: str,
        query: str,
        results: str,
    ) -> str:
        """评估工具调用结果的质量和相关性。

        在调用 ``web_search`` / ``wikipedia`` / ``read_file`` 等工具拿到结果后，
        用本工具自评结果是否充分回答了原始查询。

        Args:
            tool_name: 刚调用的工具名（如 ``"web_search"``）。
            query: 原始查询。
            results: 工具返回结果（多条用换行分隔）。

        Returns:
            JSON 字符串 ``{"verdict": "ok"|"retry"|"fallback", "score": 0-1, "reasoning": "..."}``。
            ``ok`` = 结果充分，可直接用；``retry`` = 不充分，建议重试；``fallback`` = 完全不行。
        """
        import json

        eval_result = await evaluator.evaluate(
            tool_name=tool_name,
            query=query,
            results=results,
        )
        return json.dumps(
            {
                "verdict": eval_result.verdict,
                "score": eval_result.score,
                "reasoning": eval_result.reasoning,
            },
            ensure_ascii=False,
        )

    return tool_self_evaluate
