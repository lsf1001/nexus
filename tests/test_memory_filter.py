"""测试 MemoryFilter：score 阈值 + bypass 豁免 + 异常降级。

MemoryFilter 契约：
  - score >= min_score → allow=True
  - score < min_score → allow=False
  - bypass=True → 直接 allow=True（plan 强制"高 confidence 记忆豁免"）
  - 评估异常 → allow=True（不污染主流程）
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind
from nexus.backend.quality.memory_filter import (
    DEFAULT_MIN_SCORE,
    FilterDecision,
    MemoryFilter,
)
from nexus.backend.rubrics.judge import RubricJudge
from nexus.backend.rubrics.schemas import FAITHFULNESS_RUBRIC

# ==================== Fake LLM ====================


class _FakeLLM(BaseChatModel):
    """Test 用的最小 LLM：每次 ainvoke 返回预设 JSON dict。"""

    response: object = {"score": 0.9, "reasoning": "ok", "evidence": []}
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    async def _respond(self) -> str:
        self.call_count += 1
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response, ensure_ascii=False)

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        return AIMessage(content=await self._respond())


def _make_filter(score: float, reasoning: str = "测试") -> MemoryFilter:
    """构造 MemoryFilter，judge 用单 rubric + fake LLM 返指定 score。"""
    llm = _FakeLLM(response={"score": score, "reasoning": reasoning, "evidence": ["片段"]})
    judge = RubricJudge(llm=llm, rubrics=(FAITHFULNESS_RUBRIC,))
    return MemoryFilter(judge=judge)


# ==================== happy path：allow / reject ====================


@pytest.mark.asyncio
async def test_score_above_threshold_allows():
    """score=0.85 ≥ 0.7 → allow=True。"""
    filter_obj = _make_filter(0.85, "事实可信")
    decision = await filter_obj.check(value="用户喜欢 Python 编程")
    assert decision.allow is True
    assert decision.score == 0.85
    assert decision.bypassed is False
    assert decision.rejected is False


@pytest.mark.asyncio
async def test_score_below_threshold_rejects():
    """score=0.5 < 0.7 → allow=False（拒存）。"""
    filter_obj = _make_filter(0.5, "临时上下文，不应持久化")
    decision = await filter_obj.check(value="刚才我们聊到一半")
    assert decision.allow is False
    assert decision.score == 0.5
    assert decision.rejected is True
    assert "score" in decision.reason and "0.5" in decision.reason


@pytest.mark.asyncio
async def test_score_equal_to_threshold_allows():
    """score=0.7 == min_score → allow=True（>= 阈值）。"""
    filter_obj = _make_filter(0.7)
    decision = await filter_obj.check(value="边界值")
    assert decision.allow is True


# ==================== 边界：默认 min_score = 0.7 ====================


def test_default_min_score_is_07():
    """默认 min_score = 0.7（plan 强制）。"""
    assert DEFAULT_MIN_SCORE == 0.7
    # MemoryFilter() 用默认参数
    llm = _FakeLLM()
    judge = RubricJudge(llm=llm, rubrics=(FAITHFULNESS_RUBRIC,))
    filter_obj = MemoryFilter(judge=judge)
    assert filter_obj.min_score == 0.7


# ==================== bypass 豁免 ====================


@pytest.mark.asyncio
async def test_bypass_true_skips_evaluation():
    """bypass=True 时直接 allow=True，不调 judge。"""
    filter_obj = _make_filter(0.5)  # 实际不调用，但 score 很低
    decision = await filter_obj.check(value="高 confidence 记忆更新", bypass=True)
    assert decision.allow is True
    assert decision.bypassed is True
    assert "豁免" in decision.reason
    # judge 没被调
    assert filter_obj.judge.llm.call_count == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_bypass_false_evaluates_normally():
    """bypass=False（默认）时正常调 judge。"""
    filter_obj = _make_filter(0.9)
    decision = await filter_obj.check(value="测试值")
    assert decision.allow is True
    assert decision.bypassed is False


# ==================== 异常降级 ====================


@pytest.mark.asyncio
async def test_judge_exception_falls_back_to_allow():
    """Judge 全失败 → allow=True（不污染主流程）。"""

    class _AlwaysFailLLM(_FakeLLM):
        async def _respond(self) -> str:
            raise ClassifiedError(
                kind=LLMErrorKind.AUTH,
                retryable=False,
                original=Exception("auth"),
                message="[auth] unauth",
            )

    judge = RubricJudge(llm=_AlwaysFailLLM(), rubrics=(FAITHFULNESS_RUBRIC,))
    filter_obj = MemoryFilter(judge=judge)
    decision = await filter_obj.check(value="test")
    assert decision.allow is True  # 降级放行
    assert "评估异常" in decision.reason


# ==================== 构造期校验 ====================


def test_invalid_min_score_raises():
    """min_score 越界 → ValueError。"""
    judge = RubricJudge(llm=_FakeLLM(), rubrics=(FAITHFULNESS_RUBRIC,))
    with pytest.raises(ValueError, match=r"min_score 必须在"):
        MemoryFilter(judge=judge, min_score=1.5)
    with pytest.raises(ValueError, match=r"min_score 必须在"):
        MemoryFilter(judge=judge, min_score=-0.1)


# ==================== 自定义 rubric ====================


@pytest.mark.asyncio
async def test_custom_rubric_name_used_in_lookup():
    """自定义 rubric 时，按 rubric.name 找对应 score。"""
    from dataclasses import replace

    # 构造一个自定义 rubric（name 不同）
    custom_rubric = replace(FAITHFULNESS_RUBRIC, name="memory_quality")
    llm = _FakeLLM(response={"score": 0.8, "reasoning": "记忆质量好", "evidence": []})
    judge = RubricJudge(llm=llm, rubrics=(custom_rubric,))
    filter_obj = MemoryFilter(judge=judge, rubric=custom_rubric)
    decision = await filter_obj.check(value="test")
    # 找到 memory_quality score=0.8 ≥ 0.7 → allow
    assert decision.allow is True
    assert decision.score == 0.8


# ==================== 不可变 ====================


def test_filter_decision_is_frozen():
    """FilterDecision 是 frozen=True，构造后不能改字段。"""
    decision = FilterDecision(allow=True, score=0.9, reason="ok")
    with pytest.raises((AttributeError, Exception)):
        decision.allow = False  # type: ignore[misc]


def test_memory_filter_is_frozen():
    """MemoryFilter 是 frozen=True，构造后不能改字段。"""
    judge = RubricJudge(llm=_FakeLLM(), rubrics=(FAITHFULNESS_RUBRIC,))
    filter_obj = MemoryFilter(judge=judge)
    with pytest.raises((AttributeError, Exception)):
        filter_obj.min_score = 0.5  # type: ignore[misc]
