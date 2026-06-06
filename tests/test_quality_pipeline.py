"""测试 QualityPipeline：ACCEPT / REPAIR 重生 / REJECT 三条主路径。

QualityPipeline 契约：
  - ACCEPT → 返回原 raw_response，verdict=ACCEPT
  - REPAIR + 重生后 ACCEPT → 返回重生文本，verdict=ACCEPT，repair_attempted=True
  - REPAIR + 重生后仍不通过 → REJECT fallback，verdict=REJECT
  - REJECT → fallback 文本，verdict=REJECT
  - Judge 全失败 → 降级 REJECT，不抛异常
  - 主 LLM 失败 → 降级 REJECT，不抛异常
  - 写 quality_scores 表（mock save_quality_score）
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from nexus.backend.quality.pipeline import FinalResponse, QualityPipeline
from nexus.backend.rubrics.judge import RubricJudge
from nexus.backend.rubrics.repair import RepairStrategy
from nexus.backend.rubrics.schemas import (
    DEFAULT_RUBRICS,
    RubricVerdict,
)

# ==================== Fake LLM（复用 test_rubric_judge 的 _FakeLLM 模板） ====================


class _FakeLLM(BaseChatModel):
    """共享 fake LLM 模板：与 test_rubric_judge._FakeLLM 行为一致。

    子类 override ``_respond`` 即可。
    """

    response: object = {"score": 0.9, "reasoning": "ok", "evidence": []}
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    async def _respond(self) -> str:
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response, ensure_ascii=False)

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        self.call_count += 1
        return AIMessage(content=await self._respond())


class _QueueLLM(_FakeLLM):
    """按调用次数返回预设响应（pipeline 用的 main LLM）。"""

    responses: list[str] = ["默认回复"]

    async def _respond(self) -> str:
        if not self.responses:
            return ""
        idx = min(self.call_count - 1, len(self.responses) - 1)
        return self.responses[idx]


# ==================== 工厂函数 ====================


def _make_judge_with_responses(responses_per_round: list[dict]) -> RubricJudge:
    """构造 RubricJudge，mock LLM 按"轮次"返回不同 score dict。

    Args:
        responses_per_round: 每一轮（一次 judge 全部 rubric 评分算一轮）
            返回的 LLM 响应。每个元素是单个 dict
            ``{"score": float, "reasoning": str, "evidence": list}``；
            judge 内 4 个 rubric 并发调用都用同一 dict（即每轮一个统一 score）。
    """
    round_idx = [0]

    class _RoundLLM(_FakeLLM):
        async def _respond(self) -> str:
            idx = min(round_idx[0], len(responses_per_round) - 1)
            round_idx[0] += 1
            return json.dumps(responses_per_round[idx], ensure_ascii=False)

    llm = _RoundLLM()
    return RubricJudge(llm=llm, rubrics=DEFAULT_RUBRICS)


def _default_rubric_responses(score: float, reasoning: str = "ok") -> dict:
    """构造单个 LLM 响应 dict（4 个 rubric 共用）。"""
    return {"score": score, "reasoning": reasoning, "evidence": ["片段"]}


def _make_pipeline(judge: RubricJudge, main_llm: BaseChatModel, session_id: str = "test-session") -> QualityPipeline:
    """构造 QualityPipeline，session_id 用于写 quality_scores。"""
    strategy = RepairStrategy(safety_veto=False)  # 测试中关闭 safety veto 以便精确控制
    return QualityPipeline(
        judge=judge,
        repair_strategy=strategy,
        main_llm=main_llm,
        session_id=session_id,
    )


# ==================== ACCEPT 路径 ====================


@pytest.mark.asyncio
async def test_accept_path_returns_raw_response_directly():
    """所有维度都高分 → ACCEPT → 返回原 raw_response，repair_attempted=False。"""
    judge = _make_judge_with_responses([_default_rubric_responses(0.95)])
    main_llm = _QueueLLM(responses=["重生文本"])
    pipeline = _make_pipeline(judge, main_llm)

    with patch("nexus.backend.quality.pipeline.save_quality_score") as mock_save:
        result = await pipeline.run_with_quality(
            question="什么是 Python？",
            raw_response="Python 是一种解释型编程语言。",
        )

    assert isinstance(result, FinalResponse)
    assert result.verdict == RubricVerdict.ACCEPT
    assert result.response_text == "Python 是一种解释型编程语言。"
    assert result.repair_attempted is False
    assert len(result.scores) == 4
    # 4 个维度写库 = 4 次 save
    assert mock_save.call_count == 4
    # 主 LLM 没被调（无需重生）
    assert main_llm.call_count == 0


# ==================== REPAIR 路径 ====================


@pytest.mark.asyncio
async def test_repair_path_regenerates_and_returns_new_text():
    """首次评分失败 → REPAIR → 调主 LLM → 二次评分通过 → 返回重生文本。"""
    # 第 1 轮：分数低（触发 repair），第 2 轮：高分（accept）
    judge = _make_judge_with_responses([
        _default_rubric_responses(0.5, "不太好"),  # 触发 repair
        _default_rubric_responses(0.95, "改进后"),  # 通过
    ])
    main_llm = _QueueLLM(responses=["重生后的高质量回答"])
    pipeline = _make_pipeline(judge, main_llm)

    with patch("nexus.backend.quality.pipeline.save_quality_score") as mock_save:
        result = await pipeline.run_with_quality(
            question="什么是 Python？",
            raw_response="Python 是同步的语言（错误）",
        )

    assert result.verdict == RubricVerdict.ACCEPT
    assert result.repair_attempted is True
    assert result.response_text == "重生后的高质量回答"
    # 主 LLM 被调 1 次
    assert main_llm.call_count == 1
    # 写库 2 轮 × 4 维度 = 8 次
    assert mock_save.call_count == 8


@pytest.mark.asyncio
async def test_repair_then_still_repair_returns_reject():
    """repair 后二次评分仍 REPAIR（attempt 已用尽）→ REJECT fallback。"""
    judge = _make_judge_with_responses([
        _default_rubric_responses(0.5, "差"),   # 首次 → REPAIR
        _default_rubric_responses(0.7, "还行"),  # 二次 → 介于 repair/accept，仍 REPAIR
    ])
    main_llm = _QueueLLM(responses=["重生后还行"])
    pipeline = _make_pipeline(judge, main_llm)

    with patch("nexus.backend.quality.pipeline.save_quality_score"):
        result = await pipeline.run_with_quality(
            question="q", raw_response="r1",
        )

    # RepairStrategy(attempt_count=1) 时直接 REJECT（max_repair_attempts=1）
    assert result.verdict == RubricVerdict.REJECT
    assert result.repair_attempted is True
    # fallback 文本（不是 raw_response 也不是重生文本）
    assert "答得不够好" in result.response_text or "抱歉" in result.response_text


@pytest.mark.asyncio
async def test_repair_regenerate_llm_failure_falls_back_to_reject():
    """主 LLM 重生时抛异常 → 降级 REJECT，不抛。"""
    judge = _make_judge_with_responses([_default_rubric_responses(0.5)])

    class _FailingLLM(_FakeLLM):
        async def _respond(self) -> str:
            raise RuntimeError("主 LLM 罢工")

    main_llm = _FailingLLM()
    pipeline = _make_pipeline(judge, main_llm)

    with patch("nexus.backend.quality.pipeline.save_quality_score"):
        result = await pipeline.run_with_quality(question="q", raw_response="r1")

    assert result.verdict == RubricVerdict.REJECT
    assert result.repair_attempted is True
    assert "抱歉" in result.response_text or "答得不够好" in result.response_text


# ==================== REJECT 路径 ====================


@pytest.mark.asyncio
async def test_reject_path_returns_fallback_text():
    """REJECT → 返回 fallback 文本 + verdict=REJECT + repair_attempted=False。"""
    # 用 safety veto：safety < 0.5 触发 REJECT
    safety_low = {
        "score": 0.3, "reasoning": "有害内容", "evidence": ["危险建议"],
    }
    judge = _make_judge_with_responses([safety_low])
    main_llm = _QueueLLM(responses=["unused"])
    # 用 safety_veto=True 的策略
    strategy = RepairStrategy(safety_veto=True)
    pipeline = QualityPipeline(judge=judge, repair_strategy=strategy, main_llm=main_llm, session_id="s")

    with patch("nexus.backend.quality.pipeline.save_quality_score"):
        result = await pipeline.run_with_quality(question="q", raw_response="r")

    assert result.verdict == RubricVerdict.REJECT
    assert result.repair_attempted is False
    # 不应调主 LLM
    assert main_llm.call_count == 0
    assert "抱歉" in result.response_text or "答得不够好" in result.response_text


# ==================== 异常降级 ====================


@pytest.mark.asyncio
async def test_judge_unavailable_degrades_to_reject():
    """RubricJudge 全失败（抛 RubricJudgeError）→ 降级 REJECT，不抛。"""
    from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind

    class _AlwaysFailLLM(_FakeLLM):
        async def _respond(self) -> str:
            raise ClassifiedError(
                kind=LLMErrorKind.AUTH,
                retryable=False,
                original=Exception("auth"),
                message="[auth] unauth",
            )

    judge = RubricJudge(llm=_AlwaysFailLLM(), rubrics=DEFAULT_RUBRICS)
    main_llm = _QueueLLM(responses=["unused"])
    pipeline = _make_pipeline(judge, main_llm)

    with patch("nexus.backend.quality.pipeline.save_quality_score"):
        result = await pipeline.run_with_quality(question="q", raw_response="r")

    assert result.verdict == RubricVerdict.REJECT
    assert "评分服务不可用" in result.reasoning


# ==================== 数据库写入 ====================


@pytest.mark.asyncio
async def test_quality_scores_written_with_correct_verdict():
    """ACCEPT 路径：每条 score 写入 quality_scores，verdict='accept'。"""
    judge = _make_judge_with_responses([_default_rubric_responses(0.9)])
    main_llm = _QueueLLM(responses=["unused"])
    pipeline = _make_pipeline(judge, main_llm, session_id="session-xyz")

    with patch("nexus.backend.quality.pipeline.save_quality_score") as mock_save:
        await pipeline.run_with_quality(question="q", raw_response="r")

    assert mock_save.call_count == 4
    for call in mock_save.call_args_list:
        kwargs = call.kwargs
        assert kwargs["session_id"] == "session-xyz"
        assert kwargs["verdict"] == "accept"
        assert 0.0 <= kwargs["score"] <= 1.0
        assert isinstance(kwargs["rubric"], str)


@pytest.mark.asyncio
async def test_repair_round_persists_with_prefix():
    """REPAIR 重生轮的 score 用 [repair] 前缀标识（区分两轮）。"""
    judge = _make_judge_with_responses([
        _default_rubric_responses(0.5, "差"),
        _default_rubric_responses(0.9, "好"),
    ])
    main_llm = _QueueLLM(responses=["重生"])
    pipeline = _make_pipeline(judge, main_llm, session_id="s")

    with patch("nexus.backend.quality.pipeline.save_quality_score") as mock_save:
        await pipeline.run_with_quality(question="q", raw_response="r")

    # 4 + 4 = 8 次 save；后 4 次 reasoning 含 [repair] 前缀
    assert mock_save.call_count == 8
    second_round = mock_save.call_args_list[4:]
    for call in second_round:
        reasoning = call.kwargs["reasoning"]
        assert reasoning.startswith("[repair] ") or "好" in reasoning


@pytest.mark.asyncio
async def test_no_session_id_skips_persistence():
    """无 session_id 时不写库（测试场景或临时调用）。"""
    judge = _make_judge_with_responses([_default_rubric_responses(0.9)])
    main_llm = _QueueLLM(responses=["unused"])
    pipeline = _make_pipeline(judge, main_llm, session_id="")

    with patch("nexus.backend.quality.pipeline.save_quality_score") as mock_save:
        result = await pipeline.run_with_quality(question="q", raw_response="r")

    assert result.verdict == RubricVerdict.ACCEPT
    assert mock_save.call_count == 0


# ==================== 边界 ====================


def test_pipeline_exposes_judge_and_strategy_and_llm():
    """公开属性 judge / repair_strategy / main_llm / session_id 可读。"""
    judge = _make_judge_with_responses([_default_rubric_responses(0.9)])
    main_llm = _QueueLLM(responses=["unused"])
    pipeline = _make_pipeline(judge, main_llm, session_id="s1")
    assert pipeline.judge is judge
    assert pipeline.main_llm is main_llm
    assert pipeline.session_id == "s1"


def test_set_session_id_updates_for_next_call():
    """set_session_id 改 session_id，下一次 run 用新值。"""
    judge = _make_judge_with_responses([_default_rubric_responses(0.9)])
    main_llm = _QueueLLM(responses=["unused"])
    pipeline = _make_pipeline(judge, main_llm, session_id="s1")
    pipeline.set_session_id("s2")
    assert pipeline.session_id == "s2"


def test_final_response_helpers():
    """FinalResponse.accepted / rejected 布尔属性正确。"""
    accept = FinalResponse("text", RubricVerdict.ACCEPT, "ok")
    assert accept.accepted is True
    assert accept.rejected is False
    reject = FinalResponse("text", RubricVerdict.REJECT, "no")
    assert reject.accepted is False
    assert reject.rejected is True
    repair = FinalResponse("text", RubricVerdict.REPAIR, "fix")
    assert repair.accepted is False
    assert repair.rejected is False
