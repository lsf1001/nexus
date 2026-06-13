"""Rubric 数据结构：评分维度定义、单维度结果、综合判定。

本模块是 Phase 2 (Rubrics) 的基础层——只描述"评分维度"与"评分结果"
的数据形态与判定规则，不涉及 LLM 调用与持久化。

设计要点：
  - 所有数据类 :class:`Rubric` / :class:`Score` / :class:`RubricVerdictResult`
    均使用 ``frozen=True``，避免下游意外改共享配置（CLAUDE.md §11 不可变优先）。
  - 阈值校验放在 :meth:`Rubric.__post_init__`，构造期就拦截非法配置，
    不让坏值流入后续 Task。
  - 默认可变参数一律改为不可变（``frozenset`` / ``tuple`` / ``Final``）。
  - 不引入 LLM / LangChain / tenacity，避免与上层耦合（CLAUDE.md §14）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "RubricVerdict",
    "Rubric",
    "Score",
    "RubricVerdictResult",
    "FAITHFULNESS_RUBRIC",
    "RELEVANCE_RUBRIC",
    "SAFETY_RUBRIC",
    "TOOL_CORRECTNESS_RUBRIC",
    "DEFAULT_RUBRICS",
]


# ==================== 枚举 ====================


class RubricVerdict(StrEnum):
    """对一次响应的最终评分决定（per-rubric 或综合）。"""

    ACCEPT = "accept"  # 直接接受：存入历史 / 喂给用户
    REPAIR = "repair"  # 触发 repair：重新生成后再判
    REJECT = "reject"  # 拒答：告知用户"这个问题我答得不好"

    @classmethod
    def from_score(
        cls,
        score: float,
        threshold_accept: float = 0.8,
        threshold_repair: float = 0.6,
    ) -> RubricVerdict:
        """根据单个 Score 与阈值判定 verdict（per-rubric 判定入口）。

        判定规则（高阈值优先）：
          - ``score >= threshold_accept`` → :attr:`ACCEPT`
          - ``score >= threshold_repair`` → :attr:`REPAIR`
          - 否则 → :attr:`REJECT`

        Args:
            score: 0.0-1.0 的单维度评分。
            threshold_accept: 达到此分视为 ACCEPT。
            threshold_repair: 达到此分（但低于 accept）视为 REPAIR。

        Returns:
            对应的 :class:`RubricVerdict`。
        """
        if score >= threshold_accept:
            return cls.ACCEPT
        if score >= threshold_repair:
            return cls.REPAIR
        return cls.REJECT


# ==================== 数据类 ====================


@dataclass(frozen=True)
class Rubric:
    """单个评分维度的定义。

    Attributes:
        name: 唯一标识，如 ``"faithfulness"``，对应 :attr:`Score.rubric_name`。
        weight: 评分权重，区间 ``[0, 1]``；各 Rubric 权重之和等于 ``1.0``
            由调用方保证，本类不做总和校验（避免与元评估 Task 2.9 冲突）。
        prompt: 给 Judge LLM 的中文指令；当前 Task 留空字符串占位，
            由 Task 2.2 填充。
        accept_threshold: 达到此分视为 ACCEPT，区间 ``[0, 1]``。
        repair_threshold: 达到此分（但低于 accept）视为 REPAIR，区间
            ``[0, accept_threshold]``。
    """

    name: str
    weight: float
    prompt: str
    accept_threshold: float = 0.8
    repair_threshold: float = 0.6

    def __post_init__(self) -> None:
        """构造期校验：name 非空 / weight 范围 / 阈值层级合法。"""
        if not self.name:
            raise ValueError("Rubric.name 不能为空")
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError(f"Rubric.weight 必须在 [0, 1]，当前 {self.weight}")
        if not (0.0 <= self.repair_threshold <= self.accept_threshold <= 1.0):
            raise ValueError(
                f"Rubric threshold 不合法: repair={self.repair_threshold} <= "
                f"accept={self.accept_threshold}，且都在 [0, 1]"
            )


@dataclass(frozen=True)
class Score:
    """单个 Rubric 对一次响应的评分结果。

    Attributes:
        rubric_name: 对应 :attr:`Rubric.name`。
        score: 0.0-1.0。
        reasoning: Judge LLM 的解释（中文）。
        evidence: 引用的原文片段，使用 tuple 保证不可变。
    """

    rubric_name: str
    score: float
    reasoning: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """构造期校验：score 必须在 [0, 1]。"""
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"Score.score 必须在 [0, 1]，当前 {self.score}")


@dataclass(frozen=True)
class RubricVerdictResult:
    """对一次响应的综合判定结果。

    Attributes:
        verdict: 综合 verdict（综合各 Rubric 后由 pipeline 给出）。
        scores: 各 Rubric 的 :class:`Score`。
        reasoning: 综合解释（默认由 pipeline 拼接各 Score.reasoning）。
    """

    verdict: RubricVerdict
    scores: tuple[Score, ...]
    reasoning: str = ""

    @property
    def aggregate_score(self) -> float:
        """算术平均分（各 Score 的简单平均；权重加权由上层按 Rubric 列表计算）。

        Returns:
            ``sum(scores) / len(scores)``；空 scores 时返回 ``0.0``，
            避免除零。
        """
        if not self.scores:
            return 0.0
        return sum(s.score for s in self.scores) / len(self.scores)


# ==================== 内置 4 个 Rubric ====================
#
# prompt 字段留空字符串占位，由 Task 2.2 填充中文判官指令。
# 阈值是初值，后续 Task 2.9 meta-eval 后可能调整。
# 权重合计 = 0.35 + 0.25 + 0.30 + 0.10 = 1.00。

FAITHFULNESS_RUBRIC: Final[Rubric] = Rubric(
    name="faithfulness",
    weight=0.35,
    prompt="",  # Task 2.2 填充中文判官指令
    accept_threshold=0.8,
    repair_threshold=0.6,
)

RELEVANCE_RUBRIC: Final[Rubric] = Rubric(
    name="relevance",
    weight=0.25,
    prompt="",
    accept_threshold=0.8,
    repair_threshold=0.6,
)

SAFETY_RUBRIC: Final[Rubric] = Rubric(
    name="safety",
    weight=0.30,
    prompt="",
    # 安全维度阈值更严格：放行门槛 0.9，repair 门槛 0.7。
    accept_threshold=0.9,
    repair_threshold=0.7,
)

TOOL_CORRECTNESS_RUBRIC: Final[Rubric] = Rubric(
    name="tool_correctness",
    weight=0.10,
    prompt="",
    accept_threshold=0.8,
    repair_threshold=0.6,
)

DEFAULT_RUBRICS: Final[tuple[Rubric, ...]] = (
    FAITHFULNESS_RUBRIC,
    RELEVANCE_RUBRIC,
    SAFETY_RUBRIC,
    TOOL_CORRECTNESS_RUBRIC,
)
