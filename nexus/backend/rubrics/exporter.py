"""Rubric 偏好数据导出：把 quality_scores 历史转为 DPO / KTO 训练数据。

本模块是 Phase 2 (Rubrics) Task 2.8 的实现——把 Nexus 收集的
``quality_scores`` 历史（每条含 session_id、prompt、response、score、
verdict）转成 LLM 蒸馏训练用的偏好数据。

输出格式：
  - **DPO**（Direct Preference Optimization）：每行一个
    ``{"prompt": ..., "chosen": ..., "rejected": ...}`` JSON。
  - **KTO**（Kahneman-Tversky Optimization）：每行一个
    ``{"prompt": ..., "completion": ..., "label": true|false}`` JSON。
    ``label=True`` 表示 chosen；``False`` 表示 rejected。

设计要点：
  - **数据驱动**：exporter 接受 :class:`PreferenceRecord` 列表输入
    （由调用方从 DB / quality_scores 拉取），不直接绑定 DB schema。
  - **score gap 过滤**：默认仅保留 ``|accepted.score - rejected.score| >= 0.3``
    的 pair（plan 强制），保证训练信号强。
  - **不可变**（CLAUDE.md §11）：records 在写入时转 tuple。
  - **类型注解**：完整标注。
  - **无 LLM 依赖**：本模块是纯数据转换 + 文件 IO。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "PreferenceRecord",
    "PreferenceExporter",
    "DEFAULT_MIN_SCORE_GAP",
]


logger = logging.getLogger(__name__)


# 默认 score gap 过滤阈值（plan 强制 ≥ 0.3）
DEFAULT_MIN_SCORE_GAP: Final[float] = 0.3


# ==================== 数据类 ====================


@dataclass(frozen=True)
class PreferenceRecord:
    """单条偏好数据（同一 prompt 的"高 vs 低"两个候选回复）。

    Attributes:
        prompt: 用户问题 / 上下文。
        accepted: 高分回复（被 RubricJudge 接受的那一条）。
        accepted_score: accepted 的 0.0-1.0 综合分。
        rejected: 低分回复（被拒的那一条）。
        rejected_score: rejected 的 0.0-1.0 综合分。
        session_id: 关联会话 ID（可空）。
        rubric_name: 触发判定的 rubric（可空；多个时取综合或第一个）。
    """

    prompt: str
    accepted: str
    accepted_score: float
    rejected: str
    rejected_score: float
    session_id: str = ""
    rubric_name: str = ""

    @property
    def score_gap(self) -> float:
        """accepted_score - rejected_score（应 >= min_score_gap）。"""
        return self.accepted_score - self.rejected_score

    def passes_gap(self, min_gap: float) -> bool:
        """score_gap >= min_gap 时通过过滤。"""
        return self.score_gap >= min_gap


# ==================== 主类 ====================


class PreferenceExporter:
    """偏好数据导出器：``PreferenceRecord`` 列表 → DPO / KTO jsonl 文件。

    Attributes:
        min_score_gap: 默认 score gap 过滤阈值；调用方可在 ``export_xxx``
            时覆盖。
    """

    def __init__(self, min_score_gap: float = DEFAULT_MIN_SCORE_GAP) -> None:
        """初始化导出器。

        Args:
            min_score_gap: 默认 score gap 阈值；``export_dpo/kto`` 调
                用时可单独覆盖。

        Raises:
            ValueError: 阈值非 [0, 1] 区间。
        """
        if not (0.0 <= min_score_gap <= 1.0):
            raise ValueError(f"min_score_gap 必须在 [0, 1]，当前 {min_score_gap}")
        self._min_score_gap = min_score_gap

    @property
    def min_score_gap(self) -> float:
        """当前默认 score gap 阈值。"""
        return self._min_score_gap

    # ------------------------------------------------------------------
    # 导出 API
    # ------------------------------------------------------------------

    def export_dpo(
        self,
        records: Iterable[PreferenceRecord],
        output_path: str | Path,
        min_score_gap: float | None = None,
    ) -> int:
        """导出为 DPO 格式 jsonl。

        每行一个 JSON：``{"prompt": ..., "chosen": ..., "rejected": ...}``。

        Args:
            records: 偏好数据列表。
            output_path: 输出文件路径；父目录不存在会自动创建。
            min_score_gap: 覆盖默认 score gap 阈值；``None`` 用构造时的值。

        Returns:
            实际写入文件的记录数（过滤后）。
        """
        gap = self._min_score_gap if min_score_gap is None else min_score_gap
        filtered = self._filter(records, gap)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for record in filtered:
                line = {
                    "prompt": record.prompt,
                    "chosen": record.accepted,
                    "rejected": record.rejected,
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        logger.info("导出 DPO: %d 条 → %s", len(filtered), path)
        return len(filtered)

    def export_kto(
        self,
        records: Iterable[PreferenceRecord],
        output_path: str | Path,
        min_score_gap: float | None = None,
    ) -> int:
        """导出为 KTO 格式 jsonl（每条偏好拆成两行：True + False）。

        每行一个 JSON：``{"prompt": ..., "completion": ..., "label": bool}``。
        每条 ``PreferenceRecord`` 拆为两行（accepted=true, rejected=false）。

        Args:
            records: 偏好数据列表。
            output_path: 输出文件路径。
            min_score_gap: 覆盖默认 score gap 阈值。

        Returns:
            实际写入文件的行数（过滤后，每条 record × 2）。
        """
        gap = self._min_score_gap if min_score_gap is None else min_score_gap
        filtered = self._filter(records, gap)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("w", encoding="utf-8") as f:
            for record in filtered:
                for completion, label in (
                    (record.accepted, True),
                    (record.rejected, False),
                ):
                    line = {
                        "prompt": record.prompt,
                        "completion": completion,
                        "label": label,
                    }
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
                    written += 1
        logger.info("导出 KTO: %d 条记录 (%d 行) → %s", len(filtered), written, path)
        return written

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _filter(
        records: Iterable[PreferenceRecord],
        min_gap: float,
    ) -> list[PreferenceRecord]:
        """过滤 score gap < min_gap 的记录；空 prompt / 空 response 也跳过。"""
        result: list[PreferenceRecord] = []
        for record in records:
            if not record.passes_gap(min_gap):
                continue
            if not record.prompt.strip() or not record.accepted.strip() or not record.rejected.strip():
                continue
            result.append(record)
        return result


# ==================== CLI 注册 ====================
# 历史: register_export_command() 2026-06 随 nexus/cli/ 整体删除。
# 偏好导出请直接调 PreferenceExporter.export_dpo / export_kto,或走
# 未来 APP 端 UI。
