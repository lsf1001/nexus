"""测试 ToolSelfEvaluator：ok / retry / fallback 三档决策 + 异常降级 + 工具包装。

ToolSelfEvaluator 契约：
  - score >= retry_threshold → verdict="ok"
  - fallback_threshold ≤ score < retry_threshold → verdict="retry"
  - score < fallback_threshold → verdict="fallback"
  - evaluator 内部异常 → verdict="ok"（不污染主流程）
  - build_tool_self_eval_tool 返回的 LangChain tool 可用 ainvoke
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from nexus.backend.rubrics.tool_evaluator import (
    ToolSelfEvaluator,
    build_tool_self_eval_tool,
)

# ==================== Fake LLM（与 quality pipeline 复用相同模式） ====================


class _FakeLLM(BaseChatModel):
    """Test 用的最小 LLM：返回预设 JSON dict 列表（每次 ainvoke 用下一个）。"""

    responses: list[dict] = [{"score": 0.8, "reasoning": "ok", "evidence": []}]
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    async def _respond(self) -> str:
        idx = min(self.call_count, len(self.responses) - 1)
        self.call_count += 1
        return json.dumps(self.responses[idx], ensure_ascii=False)

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        return AIMessage(content=await self._respond())


def _make_evaluator(score: float, reasoning: str = "测试") -> ToolSelfEvaluator:
    """构造 ToolSelfEvaluator，rubric judge 用单 rubric + fake LLM 返指定 score。"""
    from nexus.backend.rubrics.judge import RubricJudge
    from nexus.backend.rubrics.schemas import TOOL_CORRECTNESS_RUBRIC

    llm = _FakeLLM(responses=[{"score": score, "reasoning": reasoning, "evidence": ["片段"]}])
    judge = RubricJudge(llm=llm, rubrics=(TOOL_CORRECTNESS_RUBRIC,))
    return ToolSelfEvaluator(judge=judge)


# ==================== happy path：verdict 决策 ====================


@pytest.mark.asyncio
async def test_score_above_retry_threshold_returns_ok():
    """score=0.8 ≥ retry_threshold (0.6) → verdict="ok"。"""
    evaluator = _make_evaluator(0.8)
    result = await evaluator.evaluate(
        tool_name="web_search",
        query="北京天气",
        results=["今天北京 25 度，晴"],
    )
    assert result.verdict == "ok"
    assert result.score == 0.8
    assert result.ok is True
    assert result.should_retry is False
    assert result.should_fallback is False


@pytest.mark.asyncio
async def test_score_between_thresholds_returns_retry():
    """score=0.5 在 [fallback=0.3, retry=0.6) → verdict="retry"。"""
    evaluator = _make_evaluator(0.5, "结果不充分")
    result = await evaluator.evaluate(
        tool_name="web_search",
        query="北京天气",
        results=["无相关结果"],
    )
    assert result.verdict == "retry"
    assert result.should_retry is True
    assert result.ok is False
    assert result.should_fallback is False


@pytest.mark.asyncio
async def test_score_below_fallback_threshold_returns_fallback():
    """score=0.2 < fallback_threshold (0.3) → verdict="fallback"。"""
    evaluator = _make_evaluator(0.2, "完全无关")
    result = await evaluator.evaluate(
        tool_name="web_search",
        query="北京天气",
        results=["Python 教程"],
    )
    assert result.verdict == "fallback"
    assert result.should_fallback is True
    assert result.ok is False
    assert result.should_retry is False


# ==================== 边界 ====================


@pytest.mark.asyncio
async def test_score_equal_to_retry_threshold_returns_ok():
    """score=0.6 == retry_threshold → "ok"（>= 阈值）。"""
    evaluator = _make_evaluator(0.6)
    result = await evaluator.evaluate(
        tool_name="web_search", query="q", results=["r"]
    )
    assert result.verdict == "ok"


@pytest.mark.asyncio
async def test_score_equal_to_fallback_threshold_returns_retry():
    """score=0.3 == fallback_threshold → "retry"（>= fallback）。"""
    evaluator = _make_evaluator(0.3)
    result = await evaluator.evaluate(
        tool_name="web_search", query="q", results=["r"]
    )
    assert result.verdict == "retry"


# ==================== 输入归一化 ====================


@pytest.mark.asyncio
async def test_results_accepts_single_string():
    """results 可以是单字符串（单条结果）。"""
    evaluator = _make_evaluator(0.9)
    result = await evaluator.evaluate(
        tool_name="wikipedia", query="q", results="单条结果"
    )
    assert result.verdict == "ok"
    # judge LLM 被调 1 次（rubric 1 个）
    assert evaluator.judge.rubrics[0].name == "tool_correctness"


@pytest.mark.asyncio
async def test_results_accepts_string_list():
    """results 可以是字符串列表（多条结果）。"""
    evaluator = _make_evaluator(0.9)
    result = await evaluator.evaluate(
        tool_name="web_search",
        query="q",
        results=["结果 1", "结果 2", "结果 3"],
    )
    assert result.verdict == "ok"


# ==================== 异常降级 ====================


@pytest.mark.asyncio
async def test_evaluator_exception_falls_back_to_ok():
    """Judge 全失败（抛 RubricJudgeError）→ verdict="ok"，不污染主流程。"""
    from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind
    from nexus.backend.rubrics.judge import RubricJudge
    from nexus.backend.rubrics.schemas import TOOL_CORRECTNESS_RUBRIC

    class _AlwaysFailLLM(_FakeLLM):
        async def _respond(self) -> str:
            raise ClassifiedError(
                kind=LLMErrorKind.AUTH,
                retryable=False,
                original=Exception("auth"),
                message="[auth] unauth",
            )

    judge = RubricJudge(llm=_AlwaysFailLLM(), rubrics=(TOOL_CORRECTNESS_RUBRIC,))
    evaluator = ToolSelfEvaluator(judge=judge)
    result = await evaluator.evaluate(
        tool_name="web_search", query="q", results=["r"]
    )
    # 异常被降级为 ok
    assert result.verdict == "ok"
    assert "评估异常" in result.reasoning


# ==================== 构造期校验 ====================


def test_invalid_threshold_raises():
    """retry_threshold < fallback_threshold → ValueError。"""
    from nexus.backend.rubrics.judge import RubricJudge
    from nexus.backend.rubrics.schemas import TOOL_CORRECTNESS_RUBRIC

    judge = RubricJudge(llm=_FakeLLM(), rubrics=(TOOL_CORRECTNESS_RUBRIC,))
    with pytest.raises(ValueError, match="阈值不合法"):
        ToolSelfEvaluator(judge=judge, retry_threshold=0.3, fallback_threshold=0.6)


def test_threshold_above_one_raises():
    """retry_threshold > 1.0 → ValueError。"""
    from nexus.backend.rubrics.judge import RubricJudge
    from nexus.backend.rubrics.schemas import TOOL_CORRECTNESS_RUBRIC

    judge = RubricJudge(llm=_FakeLLM(), rubrics=(TOOL_CORRECTNESS_RUBRIC,))
    with pytest.raises(ValueError, match="阈值不合法"):
        ToolSelfEvaluator(judge=judge, retry_threshold=1.5)


# ==================== 工具包装 ====================


@pytest.mark.asyncio
async def test_build_tool_self_eval_tool_returns_langchain_tool():
    """build_tool_self_eval_tool 返回 LangChain BaseTool，名字为 'tool_self_evaluate'。"""
    evaluator = _make_evaluator(0.9)
    tool_obj = build_tool_self_eval_tool(evaluator)
    assert isinstance(tool_obj, BaseTool)
    assert tool_obj.name == "tool_self_evaluate"


@pytest.mark.asyncio
async def test_tool_self_evaluate_invocation_returns_json():
    """通过 .ainvoke 调用工具，返回 JSON 字符串含 verdict / score / reasoning。"""
    evaluator = _make_evaluator(0.9, "完全充分")
    tool_obj = build_tool_self_eval_tool(evaluator)
    # LangChain tool 的 ainvoke 接 dict
    raw = await tool_obj.ainvoke(
        {"tool_name": "web_search", "query": "q", "results": "r"}
    )
    data = json.loads(raw) if isinstance(raw, str) else raw
    assert data["verdict"] == "ok"
    assert data["score"] == 0.9
    assert "完全充分" in data["reasoning"]


# ==================== 不可变 ====================


def test_evaluator_is_frozen():
    """ToolSelfEvaluator 是 frozen=True，构造后不能改字段。"""
    from nexus.backend.rubrics.judge import RubricJudge
    from nexus.backend.rubrics.schemas import TOOL_CORRECTNESS_RUBRIC

    judge = RubricJudge(llm=_FakeLLM(), rubrics=(TOOL_CORRECTNESS_RUBRIC,))
    evaluator = ToolSelfEvaluator(judge=judge)
    with pytest.raises((AttributeError, Exception)):
        evaluator.retry_threshold = 0.9  # type: ignore[misc]
