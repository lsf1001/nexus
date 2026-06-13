"""Quality Pipeline：把 RubricJudge + RepairStrategy 串成主流程的"评分 → 决策 → 重生"编排。

本模块是 Phase 2 (Rubrics) 的编排层——给定一次助手的初步回复，调度
:class:`RubricJudge` 评分、:class:`RepairStrategy` 决策、视情况调主 LLM
做"修复性重生"，最终输出 :class:`FinalResponse`。

设计要点：
  - **REPAIR 触发重生**：verdict == REPAIR 时调主 LLM 重新生成（带
    repair reason 作 prompt 追加），再判一次；max_repair_attempts 由
    RepairStrategy 控制。
  - **不污染主流程**：QualityPipeline 自身异常被捕获并记日志，返回
    一个"fallback" FinalResponse（verdict=REJECT），让 ws.py / 微信等
    调用方永远不会因为 pipeline 崩而失去响应。
  - **写 quality_scores 表**：每次评分（含 repair 轮）都写一条记录，
    便于 Phase 2.8 偏好数据导出。
  - **不可变**（CLAUDE.md §11）：所有状态在构造时定，``run_with_quality``
    是纯函数式（除了写库和 LLM 调用）。
  - **类型注解完整**：所有公开方法、参数、返回都标注。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..db import save_quality_score
from ..rubrics.judge import RubricJudge, RubricJudgeError
from ..rubrics.repair import RepairStrategy
from ..rubrics.schemas import RubricVerdict, Score

__all__ = ["FinalResponse", "QualityPipeline"]


logger = logging.getLogger(__name__)


# ==================== 数据类 ====================


@dataclass(frozen=True)
class FinalResponse:
    """QualityPipeline 编排后的最终回复。

    Attributes:
        response_text: 给用户的最终文本。
        verdict: 最终综合判定（ACCEPT / REPAIR / REJECT）。
        reasoning: 决策原因（含 repair prompt，如适用）。
        scores: 触发最终 verdict 的那一次评分（含重生轮的）。
        repair_attempted: 是否经历了一次 repair 重生。
    """

    response_text: str
    verdict: RubricVerdict
    reasoning: str
    scores: tuple[Score, ...] = field(default_factory=tuple)
    repair_attempted: bool = False

    @property
    def accepted(self) -> bool:
        """是否被质量门通过（ACCEPT 或 REPAIR 后再 ACCEPT）。"""
        return self.verdict == RubricVerdict.ACCEPT

    @property
    def rejected(self) -> bool:
        """是否被质量门拒绝（REJECT，无可救药）。"""
        return self.verdict == RubricVerdict.REJECT


# ==================== 主类 ====================


# 当 verdict=REJECT 时给用户的占位文本（避免响应空白）
_REJECT_FALLBACK_TEXT: str = "抱歉，这个问题我暂时答得不够好，请换个问法试试。"


class QualityPipeline:
    """把 RubricJudge + RepairStrategy + 主 LLM 编排成"评分 → 决策 → 重生"流程。

    Attributes:
        judge: 已构造的 :class:`RubricJudge`。
        repair_strategy: 已构造的 :class:`RepairStrategy`。
        main_llm: 助手用主 LLM（用于 repair 重生时调 ``ainvoke``）。
        session_id: 当前会话 ID（写 quality_scores 表用）。
    """

    def __init__(
        self,
        judge: RubricJudge,
        repair_strategy: RepairStrategy,
        main_llm: BaseChatModel,
        session_id: str = "",
    ) -> None:
        """初始化 QualityPipeline。

        Args:
            judge: 已构造的 RubricJudge。
            repair_strategy: 已构造的 RepairStrategy。
            main_llm: 助手用主 LLM。
            session_id: 当前会话 ID（用于写 quality_scores 表）。
        """
        self._judge = judge
        self._repair = repair_strategy
        self._main_llm = main_llm
        self._session_id = session_id

    @property
    def judge(self) -> RubricJudge:
        """当前 RubricJudge。"""
        return self._judge

    @property
    def repair_strategy(self) -> RepairStrategy:
        """当前 RepairStrategy。"""
        return self._repair

    @property
    def main_llm(self) -> BaseChatModel:
        """主 LLM。"""
        return self._main_llm

    @property
    def session_id(self) -> str:
        """当前会话 ID。"""
        return self._session_id

    def set_session_id(self, session_id: str) -> None:
        """更新当前会话 ID（ws.py 在每个新消息进入时调用一次）。"""
        self._session_id = session_id

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def run_with_quality(
        self,
        question: str,
        raw_response: str,
        tool_calls: Sequence[dict] | None = None,
        message_id: str | None = None,
    ) -> FinalResponse:
        """对一次助手回复做质量门：评分 → 决策 → 可选 repair → 返回 FinalResponse。

        流程：
          1. 调 ``judge.judge(question, raw_response, tool_calls)`` 拿初始 scores。
          2. 调 ``repair_strategy.decide(scores, rubrics, attempt_count=0)``。
          3. ACCEPT → 写库 + 返回 FinalResponse(verdict=ACCEPT)。
          4. REPAIR → 调主 LLM 重生（prompt 追加 repair reason）→
             再次 judge → 再次 decide(attempt_count=1) → 根据二次 verdict
             决定入 ACCEPT / REJECT。
          5. REJECT → 写库 + 返回 FinalResponse(verdict=REJECT,
             response_text=_REJECT_FALLBACK_TEXT)。

        任何 Judge / LLM 异常都被捕获并降级为 REJECT 响应，不抛异常。

        Args:
            question: 用户问题。
            raw_response: 助手初步回复（已剥离 ``<thinking>`` 标签）。
            tool_calls: 工具调用列表（用于 RubricJudge 的 tool_correctness 评估）。

        Returns:
            :class:`FinalResponse`，含最终文本、verdict、reasoning、scores。
        """
        rubrics = self._judge.rubrics
        try:
            initial_scores = await self._judge.judge(question, raw_response, tool_calls)
        except RubricJudgeError as exc:
            logger.warning("RubricJudge 全失败，降级为 REJECT: %s", exc)
            return FinalResponse(
                response_text=_REJECT_FALLBACK_TEXT,
                verdict=RubricVerdict.REJECT,
                reasoning=f"评分服务不可用：{exc}",
                scores=(),
                repair_attempted=False,
            )

        verdict, reasoning = self._repair.decide(initial_scores, rubrics, attempt_count=0)
        self._persist_scores(initial_scores, verdict.value, reasoning, message_id=message_id)

        if verdict == RubricVerdict.ACCEPT:
            return FinalResponse(
                response_text=raw_response,
                verdict=verdict,
                reasoning=reasoning,
                scores=tuple(initial_scores),
                repair_attempted=False,
            )

        if verdict == RubricVerdict.REJECT:
            return FinalResponse(
                response_text=_REJECT_FALLBACK_TEXT,
                verdict=verdict,
                reasoning=reasoning,
                scores=tuple(initial_scores),
                repair_attempted=False,
            )

        # verdict == REPAIR：调主 LLM 重生
        regenerated = await self._regenerate(question, raw_response, reasoning)
        if regenerated is None:
            # 主 LLM 自身失败 → 降级为 REJECT
            return FinalResponse(
                response_text=_REJECT_FALLBACK_TEXT,
                verdict=RubricVerdict.REJECT,
                reasoning=f"repair 重生失败：{reasoning[:200]}",
                scores=tuple(initial_scores),
                repair_attempted=True,
            )

        # 二次评分
        try:
            second_scores = await self._judge.judge(question, regenerated, tool_calls)
        except RubricJudgeError as exc:
            logger.warning("RubricJudge 重生后仍失败: %s", exc)
            return FinalResponse(
                response_text=_REJECT_FALLBACK_TEXT,
                verdict=RubricVerdict.REJECT,
                reasoning=f"二次评分失败：{exc}",
                scores=tuple(initial_scores),
                repair_attempted=True,
            )

        second_verdict, second_reasoning = self._repair.decide(second_scores, rubrics, attempt_count=1)
        self._persist_scores(
            second_scores,
            second_verdict.value,
            second_reasoning,
            prefix="[repair] ",
            message_id=message_id,
        )

        if second_verdict == RubricVerdict.ACCEPT:
            return FinalResponse(
                response_text=regenerated,
                verdict=second_verdict,
                reasoning=second_reasoning,
                scores=tuple(second_scores),
                repair_attempted=True,
            )

        # REPAIR 仍不通过（已耗尽 attempts）→ REJECT，但保留重生文本？
        # 保守策略：仍走 fallback 文本，不暴露未通过的内容
        return FinalResponse(
            response_text=_REJECT_FALLBACK_TEXT,
            verdict=RubricVerdict.REJECT,
            reasoning=f"repair 后仍未通过：{second_reasoning}",
            scores=tuple(second_scores),
            repair_attempted=True,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _regenerate(
        self,
        question: str,
        raw_response: str,
        repair_reason: str,
    ) -> str | None:
        """调主 LLM 重生：把 repair reason 追加到 user 消息末尾。

        返回新文本；主 LLM 失败返回 ``None``。
        """
        try:
            messages = [
                SystemMessage(content="你是一个有用且事实严谨的助手。"),
                HumanMessage(
                    content=(
                        f"用户问题：{question}\n\n"
                        f"你之前的回答：{raw_response[:500]}\n\n"
                        f"【质量反馈】\n{repair_reason}\n\n"
                        f"请根据上述反馈重新回答用户问题："
                    )
                ),
            ]
            result = await self._main_llm.ainvoke(messages)
            # 兼容 AIMessage / str / dict
            content = getattr(result, "content", None)
            if content is None and isinstance(result, dict):
                content = result.get("content", "")
            text = str(content or "").strip()
            return text or None
        except Exception as exc:  # noqa: BLE001 — 边界收口
            logger.warning("主 LLM repair 重生失败: %s", exc)
            return None

    def _persist_scores(
        self,
        scores: Sequence[Score],
        verdict: str,
        reasoning: str,
        prefix: str = "",
        message_id: str | None = None,
    ) -> None:
        """把每个 Score 写一条 quality_scores 记录。

        没有 session_id 时跳过（测试场景可能不写）。
        """
        if not self._session_id:
            return
        for score in scores:
            try:
                save_quality_score(
                    session_id=self._session_id,
                    message_id=message_id,
                    rubric=score.rubric_name,
                    score=score.score,
                    verdict=verdict,
                    reasoning=prefix + (score.reasoning or reasoning)[:500],
                )
            except Exception as exc:  # noqa: BLE001 — 边界收口
                logger.warning(
                    "写 quality_scores 失败 (rubric=%s): %s",
                    score.rubric_name,
                    exc,
                )
