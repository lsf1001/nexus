"""记忆去噪：拦截 ``edit_file`` / ``write_file`` 写入 AGENTS.md 之前用 RubricJudge 评估是否值得持久化。

本模块是 Phase 2 (Rubrics) Task 2.7 的实现——在 deepagents LLM 调用
``edit_file`` / ``write_file`` 写 ``~/.nexus/AGENTS.md`` 前做
"质量门"，过滤掉幻觉、临时上下文、单次对话残留等"低价值"内容。

WHY: v0.1.0 自定义 ``save_memory`` 工具已删除(deepagents 重构后改用内置
``edit_file``)。但记忆写入仍需质量门:由 :class:`QualityGateMiddleware`
在 :meth:`awrap_tool_call` 里调 :meth:`MemoryFilter.check`,不再走旧工具。
本模块保持纯函数语义(只评估 value,不直接操作 backend),可单测。

设计要点：
  - **专用 faithfulness 维度**：用 :data:`FAITHFULNESS_RUBRIC` 单独
    评估"value 是否是可信的事实/偏好"。
  - **不污染主流程**：filter 自身异常（Judge 全失败 / 超时）→ 默认
    放行（allow=True），避免主流程因为评分服务不可用而崩。
  - **豁免机制**：已有记忆的"高 confidence"更新可豁免（plan 要求）。
    实现为 ``bypass=True`` 参数——调用方传 ``True`` 时跳过评估。
  - **不可变**（CLAUDE.md §11）：决策结果是 frozen dataclass。
  - **类型注解完整**：所有公开 API 标注。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from ..rubrics.judge import RubricJudge
from ..rubrics.schemas import FAITHFULNESS_RUBRIC, Rubric, Score

__all__ = ["MemoryFilter", "FilterDecision"]


logger = logging.getLogger(__name__)


# 默认最低分阈值（plan 强制 < 0.7 拒存）
DEFAULT_MIN_SCORE: Final[float] = 0.7


@dataclass(frozen=True)
class FilterDecision:
    """记忆去噪决策。

    Attributes:
        allow: 是否允许保存（True = 保存 / False = 拒存）。
        score: faithfulness 维度评分（0.0-1.0）。
        reason: 决策原因（中文，可作日志）。
        bypassed: 是否走豁免路径（调用方显式 bypass=True 时为 True）。
    """

    allow: bool
    score: float
    reason: str
    bypassed: bool = False

    @property
    def rejected(self) -> bool:
        """allow == False 的便捷判断。"""
        return not self.allow


@dataclass(frozen=True)
class MemoryFilter:
    """记忆去噪器:在 edit_file / write_file 写 AGENTS.md 之前评估 value 是否值得持久化。

    Attributes:
        judge: 已构造的 :class:`RubricJudge`（用 faithfulness 维度）。
        min_score: 最低分阈值；score < min_score → 拒存。默认 0.7（plan）。
        rubric: 评估用的 rubric，默认 :data:`FAITHFULNESS_RUBRIC`。
    """

    judge: RubricJudge
    min_score: float = DEFAULT_MIN_SCORE
    rubric: Rubric = FAITHFULNESS_RUBRIC

    def __post_init__(self) -> None:
        """构造期校验阈值。"""
        if not (0.0 <= self.min_score <= 1.0):
            raise ValueError(f"min_score 必须在 [0, 1]，当前 {self.min_score}")

    async def check(
        self,
        value: str,
        *,
        bypass: bool = False,
        user_context: str | None = None,
    ) -> FilterDecision:
        """评估一个待保存的 value 是否值得持久化。

        Args:
            value: 待保存的记忆值。
            bypass: 显式豁免评估（如已有"高 confidence"记忆更新），
                ``True`` 时直接放行。默认 ``False``。
            user_context: 最近用户消息摘要（可空）。填了之后 Judge 能看到
                用户的真实意图，避免把"用户明确要求写入的具体字符串"
                误判为"完全没有回答问题"。建议 1-3 条 HumanMessage 的
                ``content`` 用换行串接，单条截断到 500 字。

        Returns:
            :class:`FilterDecision`，含 allow / score / reason / bypassed。
        """
        if bypass:
            return FilterDecision(
                allow=True,
                score=1.0,
                reason="调用方显式豁免（已有高 confidence 记忆更新）",
                bypassed=True,
            )

        # 构造 question 给 judge。把"用户最近消息 + 待写入内容"放 question，
        # 让 :class:`RubricJudge` 的 user template 把它渲染到"用户问题："
        # 那行；response 字段填 value 是为了同时让 Judge 看到待评估内容
        # 独立成段、便于评分。
        #
        # WHY: 不传 user_context 时,旧版 question 写死"[记忆评估] 这条内容
        # 是否值得作为长期记忆持久化?",而 response 又恰好是用户要求的写入
        # 字符串(比如 "e2e_hitl_marker_2026")。Judge 看到的是"用户问是否
        # 持久化 / 助手只回了一个标记串",FAITHFULNESS 维度直接 0.0,工具被
        # 拒,WS 流提前结束,前端 HITL 批准后气泡空白。
        question = _build_question(value, user_context)
        try:
            scores = await self.judge.judge(
                question=question,
                response=value,
                tool_calls=None,
            )
        except Exception as exc:  # noqa: BLE001 — 边界收口
            logger.warning("MemoryFilter 评估异常，默认放行: %s", exc)
            return FilterDecision(
                allow=True,
                score=1.0,
                reason=f"评估异常：{type(exc).__name__}: {exc}",
            )

        # 找 faithfulness 维度
        faith_score = next(
            (s for s in scores if s.rubric_name == self.rubric.name),
            scores[0] if scores else None,
        )
        if faith_score is None:
            return FilterDecision(
                allow=True,
                score=1.0,
                reason="无可用评分，默认放行",
            )

        return self._decide(faith_score)

    def _decide(self, score: Score) -> FilterDecision:
        """根据 score 和阈值判定 allow。"""
        if score.score < self.min_score:
            return FilterDecision(
                allow=False,
                score=score.score,
                reason=f"score {score.score:.2f} < {self.min_score}：{score.reasoning}",
            )
        return FilterDecision(
            allow=True,
            score=score.score,
            reason=f"score {score.score:.2f} ≥ {self.min_score}",
        )


def _build_question(value: str, user_context: str | None) -> str:
    """构造喂给 :class:`RubricJudge` 的 question 字段。

    把"用户原始意图 + 待写入内容"包成一段中文,让 Judge 看到完整故事
    后按 faithfulness 维度评分。``user_context`` 缺失时退回到旧版写死
    文案,行为保持兼容。
    """
    if user_context:
        return (
            "[记忆评估] 当前对话中用户最近的消息摘要如下,助手要按这些消息的"
            "意图把对应内容写入长期记忆 AGENTS.md。\n\n"
            f"【最近用户消息】\n{user_context}\n\n"
            f"【待写入的新内容】\n{value}\n\n"
            "请评估「待写入的新内容」是否合理地服务于上述用户意图(忠实度):"
            "用户明确要写这个内容则 score=1.0;内容与用户意图完全无关/凭空"
            "捏造则 score=0.0。"
        )
    return "[记忆评估] 这条内容是否值得作为长期记忆持久化？"
