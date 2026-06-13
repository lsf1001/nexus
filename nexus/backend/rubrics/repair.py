"""Rubric 评分后的 Repair 决策策略。

本模块是 Phase 2 (Rubrics) 的决策层——给定 :class:`RubricJudge` 输出的
:class:`list[Score]` 和对应 :class:`Rubric` 列表，按规则判定
:class:`RubricVerdict`（ACCEPT / REPAIR / REJECT）并返回给上轮
主 LLM 用的 repair prompt。

设计要点：
  - **safety 一票否决**：safety score < 0.5 → 直接 REJECT，不给 repair 机会
    （避免 LLM "自我修复"成更危险内容）。Plan 强制要求。
  - **加权聚合**：综合分数 = ``Σ(score_i × weight_i)``；任一维度的绝对
    score 与 weight 加权综合分共同参与判定。
  - **repair 次数上限**：``max_repair_attempts=1`` 时，``decide`` 收到
    ``attempt_count=1`` 后即使满足 repair 条件也返回 REJECT（避免无限
    repair 循环）。Plan 强制要求。
  - **不可变**（CLAUDE.md §11）：rubrics 列表在 ``__init__`` 转 tuple；
    ``frozen=True`` 风格的状态在外部只读。
  - **类型注解**：所有公开 API 完整标注。
  - **无 LLM 依赖**：本模块是纯函数式决策，不调任何 LLM。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from .schemas import Rubric, RubricVerdict, Score

__all__ = ["RepairStrategy"]


logger = logging.getLogger(__name__)


# safety 触发一票否决的硬阈值（plan 强制 < 0.5）
_SAFETY_VETO_THRESHOLD: Final[float] = 0.5


@dataclass(frozen=True)
class RepairStrategy:
    """Rubric 评分 → verdict 决策器。

    Attributes:
        safety_veto: 是否启用 safety 一票否决；为 ``False`` 时 safety
            只走普通 repair 流程，不直接 REJECT。Plan 强制 ``True``。
        max_repair_attempts: repair 最大尝试次数；``decide`` 收到
            ``attempt_count >= max_repair_attempts`` 时即使触发 repair
            条件也返回 REJECT。
    """

    safety_veto: bool = True
    max_repair_attempts: int = 1

    def __post_init__(self) -> None:
        """构造期校验。"""
        if self.max_repair_attempts < 0:
            raise ValueError(f"max_repair_attempts 必须 >= 0，当前 {self.max_repair_attempts}")

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def decide(
        self,
        scores: Sequence[Score],
        rubrics: Sequence[Rubric],
        attempt_count: int = 0,
    ) -> tuple[RubricVerdict, str]:
        """根据 rubric 评分判定 verdict。

        Args:
            scores: RubricJudge 输出，顺序与 ``rubrics`` 对应。
            rubrics: 评分维度定义（含 weight、accept_threshold、repair_threshold）。
            attempt_count: 已发起的 repair 次数（0 表示首次评估）。

        Returns:
            ``(verdict, reasoning)``：
              - ``verdict``：``ACCEPT`` / ``REPAIR`` / ``REJECT``。
              - ``reasoning``：解释判定原因的中文文本；同时也是给主
                LLM 的 repair prompt（``verdict == REPAIR`` 时有效，
                ``ACCEPT`` / ``REJECT`` 时也保留作审计/日志）。

        Raises:
            ValueError: scores / rubrics 为空，或两者长度不匹配。
        """
        if not scores or not rubrics:
            raise ValueError("scores 和 rubrics 都不可为空")
        if len(scores) != len(rubrics):
            raise ValueError(f"scores 长度 ({len(scores)}) 与 rubrics 长度 ({len(rubrics)}) 不匹配")
        if attempt_count < 0:
            raise ValueError(f"attempt_count 必须 >= 0，当前 {attempt_count}")

        score_by_name: dict[str, Score] = {s.rubric_name: s for s in scores}
        rubric_by_name: dict[str, Rubric] = {r.name: r for r in rubrics}

        # 1) safety 一票否决（最高优先级，plan 强制）
        if self.safety_veto and "safety" in score_by_name:
            safety_score = score_by_name["safety"].score
            if safety_score < _SAFETY_VETO_THRESHOLD:
                reason = f"safety 评分 {safety_score:.2f} < {_SAFETY_VETO_THRESHOLD}，触发安全一票否决"
                logger.info("RubricRepair REJECT: %s", reason)
                return RubricVerdict.REJECT, reason

        # 2) 逐维度判定：找出所有不达 accept_threshold 的维度
        failed_accept: list[str] = []
        failed_repair: list[str] = []
        for rubric in rubrics:
            score_obj = score_by_name[rubric.name]
            if score_obj.score < rubric.accept_threshold:
                failed_accept.append(rubric.name)
                if score_obj.score < rubric.repair_threshold:
                    failed_repair.append(rubric.name)

        # 3) 全部维度 ≥ accept_threshold → ACCEPT（不论次数；plan "重试 1 次后
        #    仍 REJECT" 语义是指"仍不通过"，已通过就直接放行）
        if not failed_accept:
            aggregate = self._aggregate_weighted(score_by_name, rubric_by_name)
            reason = f"所有维度均达 accept_threshold；加权综合分 {aggregate:.2f}"
            logger.info("RubricRepair ACCEPT: %s", reason)
            return RubricVerdict.ACCEPT, reason

        # 4) 有维度不达 accept：检查 repair 次数上限
        if attempt_count >= self.max_repair_attempts:
            reason = (
                f"已 repair {attempt_count} 次，达到上限 {self.max_repair_attempts}；"
                f"仍未通过：{', '.join(failed_accept)}"
            )
            logger.info("RubricRepair REJECT (max attempts): %s", reason)
            return RubricVerdict.REJECT, reason

        # 5) 触发 REPAIR
        repair_prompt = self._build_repair_prompt(
            failed_accept=failed_accept,
            failed_repair=failed_repair,
            score_by_name=score_by_name,
            rubric_by_name=rubric_by_name,
        )
        logger.info(
            "RubricRepair REPAIR: %d 维度未达 accept（%d 低于 repair）",
            len(failed_accept),
            len(failed_repair),
        )
        return RubricVerdict.REPAIR, repair_prompt

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_failed_dimensions(
        score_by_name: dict[str, Score],
        rubric_by_name: dict[str, Rubric],
    ) -> list[str]:
        """收集低于 accept_threshold 的维度名列表。"""
        failed: list[str] = []
        for name, score in score_by_name.items():
            rubric = rubric_by_name.get(name)
            if rubric is None:
                continue
            if score.score < rubric.accept_threshold:
                failed.append(f"{name}({score.score:.2f})")
        return failed

    @staticmethod
    def _aggregate_weighted(
        score_by_name: dict[str, Score],
        rubric_by_name: dict[str, Rubric],
    ) -> float:
        """按 Rubric.weight 计算加权综合分。

        使用 ``Σ(score × weight) / Σ(weight)`` 归一化（避免权重和 != 1.0
        时偏差），与 :meth:`RubricVerdictResult.aggregate_score` 的简单
        算术平均区分开。

        Returns:
            加权综合分，区间 ``[0, 1]``。
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for name, score in score_by_name.items():
            rubric = rubric_by_name.get(name)
            if rubric is None:
                continue
            weighted_sum += score.score * rubric.weight
            total_weight += rubric.weight
        if total_weight <= 0:
            return 0.0
        return weighted_sum / total_weight

    @staticmethod
    def _build_repair_prompt(
        failed_accept: list[str],
        failed_repair: list[str],
        score_by_name: dict[str, Score],
        rubric_by_name: dict[str, Rubric],
    ) -> str:
        """构造给主 LLM 的 repair prompt：列出失败维度 + 改进建议。

        模板结构：
          1. 总体说明（"上一次回答在以下维度未达标"）
          2. 各维度详细（score、reasoning、evidence 节选）
          3. 改进要求
        """
        lines: list[str] = []
        lines.append("【上一次回答未达标的维度】")
        for name in failed_accept:
            score_obj = score_by_name[name]
            rubric = rubric_by_name[name]
            severity = "严重低于阈值" if name in failed_repair else "未达 accept 阈值"
            lines.append(f"- {name}（{severity}）：得分 {score_obj.score:.2f}，需 ≥ {rubric.accept_threshold:.2f}")
            reasoning = score_obj.reasoning.strip()
            if reasoning and reasoning != "(无解释)":
                lines.append(f"  评分员反馈：{reasoning}")
            if score_obj.evidence:
                evidence_str = "；".join(score_obj.evidence[:3])
                lines.append(f"  引用：{evidence_str}")

        lines.append("")
        lines.append("【请按以下要求改进你的回答】")
        lines.append("1. 针对上述维度，重写时优先修正失分点")
        lines.append("2. 保持原意和事实准确性，不引入新错误")
        lines.append("3. 输出仍然保持简洁，避免冗余")

        return "\n".join(lines)
