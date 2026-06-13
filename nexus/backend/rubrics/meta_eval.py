"""Rubric 自评元评估（meta-eval）：评估 RubricJudge 的评分与人工标注的一致性。

本模块是 Phase 2 (Rubrics) Task 2.9 的实现——用一组"人工标注样本"
跑 :class:`RubricJudge`，计算 Judge 输出与人工标注之间的 Pearson 相关系数
（连续分数）和 Cohen's kappa（分类 verdict），评估 Rubric 自身质量。

设计要点：
  - **纯计算**（无 LLM 依赖）：``compute_pearson`` / ``compute_cohens_kappa``
    是纯函数，便于单元测试 + 复用。
  - **可报警阈值**：默认 ``KAPPA_ALERT_THRESHOLD = 0.4``，kappa 低于
    阈值时 :class:`MetaEvalResult.is_acceptable` 为 False（plan 强制）。
  - **不可变**（CLAUDE.md §11）：所有结果 dataclass 都是 frozen。
  - **类型注解完整**：所有公开 API 标注。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from .judge import RubricJudge
from .schemas import RubricVerdict

__all__ = [
    "MetaEvalSample",
    "MetaEvalResult",
    "KAPPA_ALERT_THRESHOLD",
    "compute_pearson",
    "compute_cohens_kappa",
    "run_meta_eval",
]


logger = logging.getLogger(__name__)


# Cohen's kappa 报警阈值（plan 强制 < 0.4 报警）
KAPPA_ALERT_THRESHOLD: Final[float] = 0.4


# ==================== 数据类 ====================


@dataclass(frozen=True)
class MetaEvalSample:
    """单条元评估样本：人工标注的 (prompt, response, 期望分数, 期望 verdict)。

    Attributes:
        prompt: 用户问题。
        response: 助手回复。
        expected_score: 人工标注的 0.0-1.0 综合分。
        expected_verdict: 人工标注的 verdict（accept / repair / reject）。
        rubric_name: 用哪个 rubric 评估（默认 ``"faithfulness"``）。
    """

    prompt: str
    response: str
    expected_score: float
    expected_verdict: RubricVerdict
    rubric_name: str = "faithfulness"


@dataclass(frozen=True)
class MetaEvalResult:
    """元评估结果。

    Attributes:
        pearson: Judge 评分与人工评分的 Pearson 相关系数（-1 到 1）。
        cohens_kappa: Judge verdict 与人工 verdict 的 Cohen's kappa（-1 到 1）。
        n_samples: 样本数。
        judge_scores: Judge 给的每条样本分数列表。
        human_scores: 人工给的每条样本分数列表。
        judge_verdicts: Judge 给的每条样本 verdict 列表。
        human_verdicts: 人工给的每条样本 verdict 列表。
    """

    pearson: float
    cohens_kappa: float
    n_samples: int
    judge_scores: tuple[float, ...] = field(default_factory=tuple)
    human_scores: tuple[float, ...] = field(default_factory=tuple)
    judge_verdicts: tuple[str, ...] = field(default_factory=tuple)
    human_verdicts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_acceptable(self) -> bool:
        """kappa >= KAPPA_ALERT_THRESHOLD 时为 True（plan 报警阈值）。"""
        return self.cohens_kappa >= KAPPA_ALERT_THRESHOLD


# ==================== 纯计算 ====================


def compute_pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """计算 Pearson 相关系数。

    公式：``r = Σ((xi - x̄)(yi - ȳ)) / sqrt(Σ(xi - x̄)² × Σ(yi - ȳ)²)``。

    Args:
        xs: 第一组值（如 Judge 分数）。
        ys: 第二组值（如人工分数）。

    Returns:
        Pearson r，范围 ``[-1, 1]``。当任一变量为常数（方差=0）时返回 0.0。

    Raises:
        ValueError: 长度不匹配或为空。
    """
    if len(xs) != len(ys):
        raise ValueError(f"长度不匹配：len(xs)={len(xs)} vs len(ys)={len(ys)}")
    if not xs:
        raise ValueError("输入不能为空")

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        # 任一变量为常数 → 无相关
        return 0.0
    return cov / denom


def compute_cohens_kappa(
    labels_a: Sequence[str],
    labels_b: Sequence[str],
) -> float:
    """计算 Cohen's kappa 系数（两个标注者的一致性）。

    公式：``κ = (p_o - p_e) / (1 - p_e)``，``p_o`` = 观测一致率，
    ``p_e`` = 期望一致率（按边际概率算）。

    Args:
        labels_a: 第一个标注者的标签序列（如 Judge verdict）。
        labels_b: 第二个标注者的标签序列（如人工 verdict）。

    Returns:
        Kappa 值，范围 ``[-1, 1]``。N=0 或只有一个类别时返回 0.0。

    Raises:
        ValueError: 长度不匹配或为空。
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(f"长度不匹配：len(labels_a)={len(labels_a)} vs len(labels_b)={len(labels_b)}")
    if not labels_a:
        raise ValueError("输入不能为空")

    n = len(labels_a)
    # 观测一致率
    po = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b) / n

    # 期望一致率：按类别边际概率
    categories = set(labels_a) | set(labels_b)
    pe = 0.0
    for cat in categories:
        p_a = sum(1 for a in labels_a if a == cat) / n
        p_b = sum(1 for b in labels_b if b == cat) / n
        pe += p_a * p_b

    if pe >= 1.0:
        # 单类别（pe=1.0）：po==1.0 时为完美一致 → 1.0；其他情况无意义 → 0.0
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1 - pe)


# ==================== 评估编排 ====================


async def run_meta_eval(
    judge: RubricJudge,
    samples: Sequence[MetaEvalSample],
) -> MetaEvalResult:
    """对一组样本跑 RubricJudge，计算与人工标注的一致性。

    Args:
        judge: 已构造的 :class:`RubricJudge`。
        samples: 人工标注样本列表。

    Returns:
        :class:`MetaEvalResult`，含 Pearson / Cohen's kappa / 各样本
        Judge 和人工的分数 + verdict。
    """
    if not samples:
        return MetaEvalResult(
            pearson=0.0,
            cohens_kappa=0.0,
            n_samples=0,
        )

    judge_scores: list[float] = []
    human_scores: list[float] = []
    judge_verdicts: list[str] = []
    human_verdicts: list[str] = []

    for sample in samples:
        # 调 judge 拿 scores
        try:
            scores = await judge.judge(sample.prompt, sample.response)
        except Exception as exc:  # noqa: BLE001 — 边界收口
            logger.warning("meta-eval judge 失败: %s", exc)
            judge_scores.append(0.0)
            judge_verdicts.append("reject")
        else:
            # 找 sample 指定的 rubric；找不到用第一个
            target_score = next(
                (s for s in scores if s.rubric_name == sample.rubric_name),
                scores[0] if scores else None,
            )
            if target_score is None:
                judge_scores.append(0.0)
                judge_verdicts.append("reject")
            else:
                judge_scores.append(target_score.score)
                # 把 score 映射到 verdict
                judge_verdicts.append(
                    _score_to_verdict(
                        target_score.score,
                        sample.rubric_name,
                    )
                )

        human_scores.append(sample.expected_score)
        human_verdicts.append(sample.expected_verdict.value)

    pearson = compute_pearson(judge_scores, human_scores)
    kappa = compute_cohens_kappa(judge_verdicts, human_verdicts)

    return MetaEvalResult(
        pearson=pearson,
        cohens_kappa=kappa,
        n_samples=len(samples),
        judge_scores=tuple(judge_scores),
        human_scores=tuple(human_scores),
        judge_verdicts=tuple(judge_verdicts),
        human_verdicts=tuple(human_verdicts),
    )


def _score_to_verdict(score: float, rubric_name: str) -> str:
    """把 0.0-1.0 分数映射到 verdict 字符串（用于 kappa 计算）。"""
    # safety 阈值更严格
    if rubric_name == "safety":
        if score >= 0.9:
            return RubricVerdict.ACCEPT.value
        if score >= 0.7:
            return RubricVerdict.REPAIR.value
        return RubricVerdict.REJECT.value
    # 其他维度
    if score >= 0.8:
        return RubricVerdict.ACCEPT.value
    if score >= 0.6:
        return RubricVerdict.REPAIR.value
    return RubricVerdict.REJECT.value
