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
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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


# ==================== user_context 注入（C5 修复:HITL 批准后气泡空白）====================
#
# 根因：旧版 _build_question 写死"[记忆评估] 这条内容是否值得作为长期记忆持久化?",
# Judge 看不到 user 原始意图,把"用户明确要求写入的具体字符串"(如
# e2e_hitl_marker_2026)按 faithfulness 维度直接判 0.0,工具被拒,WS 流
# 提前结束,HITL 批准后气泡空白。
#
# 修复：把最近 user 消息 + 待写入内容拼成 question,Judge 能看到完整意图。
# 验证：传 user_context 时 judge.ainvoke 收到的 messages[1].content 必须
# 同时包含 user 消息文本 + value;不传时退回旧版写死文案,行为兼容。


class _CaptureLLM(_FakeLLM):
    """把 ainvoke 收到的 messages 全部记下来,供断言用。

    WHY: _FakeLLM 只回固定 JSON,断言 question 拼接只能通过捕获 LLM 入参。
    """

    # Pydantic field,每个实例自己的 list(不共享)
    captured_messages: list = []

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        # _respond() 增加 call_count,这里仅记录 input
        self.captured_messages.append(input)
        return AIMessage(content=await self._respond())


def _make_capture_filter(
    score: float = 0.9,
    reasoning: str = "ok",
) -> tuple[MemoryFilter, _CaptureLLM]:
    """构造一个用 _CaptureLLM 的 filter,返回 (filter, llm 实例)。

    之所以返回 llm 实例而不是 class:实例才能拿到自己的 captured_messages。
    """
    llm = _CaptureLLM(
        response={"score": score, "reasoning": reasoning, "evidence": []},
    )
    judge = RubricJudge(llm=llm, rubrics=(FAITHFULNESS_RUBRIC,))
    return MemoryFilter(judge=judge), llm


@pytest.mark.asyncio
async def test_user_context_injected_into_question():
    """传 user_context 时,Judge 收到的 question 包含 user 消息 + value。

    修复根因:旧版 Judge 看不到 user 意图 → 误判 0.0。
    """
    filter_obj, llm = _make_capture_filter(0.9)
    user_msg = "请在 AGENTS.md 末尾追加 e2e_hitl_marker_2026"
    await filter_obj.check(value="e2e_hitl_marker_2026", user_context=user_msg)

    # Judge 调了 1 次
    assert llm.captured_messages, "Judge 没被调用"
    # _build_messages 模板: system=rubric.prompt, user=user_body
    messages = llm.captured_messages[0]
    user_body = messages[1].content  # type: ignore[union-attr]
    assert user_msg in user_body, f"user 消息未注入 question: {user_body}"
    assert "e2e_hitl_marker_2026" in user_body, f"value 未注入 question: {user_body}"


@pytest.mark.asyncio
async def test_no_user_context_falls_back_to_legacy_question():
    """不传 user_context 时,question 退回旧版写死文案,行为兼容。"""
    filter_obj, llm = _make_capture_filter(0.9)
    await filter_obj.check(value="some_value")

    messages = llm.captured_messages[0]
    user_body = messages[1].content  # type: ignore[union-attr]
    # 旧版写死文案在 question 字段
    assert "[记忆评估]" in user_body
    # 旧版没有 "最近用户消息" 段
    assert "最近用户消息" not in user_body


@pytest.mark.asyncio
async def test_user_context_bypass_still_skips_judge():
    """bypass=True 仍然短路,bypass 优先级最高,user_context 不影响。"""
    filter_obj, llm = _make_capture_filter(0.0)
    decision = await filter_obj.check(
        value="x",
        bypass=True,
        user_context="无论传什么都被豁免",
    )
    assert decision.allow is True
    assert decision.bypassed is True
    # judge 没被调
    assert llm.captured_messages == []


def test_build_question_includes_user_and_value():
    """_build_question 直接断言:user 消息和 value 都进 question 字段。"""
    from nexus.backend.quality.memory_filter import _build_question

    q = _build_question("hello world", "用户说写 hello world")
    assert "用户说写 hello world" in q
    assert "hello world" in q
    assert "待写入的新内容" in q


def test_build_question_none_context_legacy_string():
    """user_context=None 时退回旧版写死文案。"""
    from nexus.backend.quality.memory_filter import _build_question

    q = _build_question("x", None)
    assert "是否值得作为长期记忆持久化" in q


# ==================== QualityGateMiddleware._extract_user_context ====================


def test_extract_user_context_empty_state_returns_none():
    """state 不是 dict / messages 空 → 返回 None(filter 退回旧版)。"""
    from nexus.backend.quality.middleware import QualityGateMiddleware

    mw = QualityGateMiddleware(
        filter=_make_filter(0.9),  # 不会真调
        protected_paths=("/tmp/dummy",),
    )
    assert mw._extract_user_context(None) is None
    assert mw._extract_user_context({}) is None
    assert mw._extract_user_context({"messages": []}) is None
    assert mw._extract_user_context({"messages": "not a list"}) is None


def test_extract_user_context_picks_humans_only():
    """只取 HumanMessage,跳过 AIMessage / ToolMessage。"""
    from nexus.backend.quality.middleware import QualityGateMiddleware

    mw = QualityGateMiddleware(
        filter=_make_filter(0.9),
        protected_paths=("/tmp/dummy",),
    )
    state = {
        "messages": [
            HumanMessage(content="第一条 user"),
            AIMessage(content="第一条 ai"),
            ToolMessage(content="tool 结果", tool_call_id="1"),
            HumanMessage(content="第二条 user"),
            HumanMessage(content="第三条 user"),
        ]
    }
    ctx = mw._extract_user_context(state)
    assert ctx is not None
    assert "第一条 user" in ctx
    assert "第二条 user" in ctx
    assert "第三条 user" in ctx
    # ai / tool 内容不进 user context
    assert "第一条 ai" not in ctx
    assert "tool 结果" not in ctx


def test_extract_user_context_truncates_long_content():
    """单条超过 500 字 / 总长超过 1500 字 → 截断标注。"""
    from nexus.backend.quality.middleware import QualityGateMiddleware

    mw = QualityGateMiddleware(
        filter=_make_filter(0.9),
        protected_paths=("/tmp/dummy",),
    )
    long_msg = "x" * 2000
    state = {"messages": [HumanMessage(content=long_msg)]}
    ctx = mw._extract_user_context(state)
    assert ctx is not None
    assert "已截断" in ctx
    # 截断后不会包含全部 2000 个 x
    assert ctx.count("x") < 2000


def test_extract_user_context_window_limit():
    """只取最近 3 条 HumanMessage,更早的忽略。"""
    from nexus.backend.quality.middleware import QualityGateMiddleware

    mw = QualityGateMiddleware(
        filter=_make_filter(0.9),
        protected_paths=("/tmp/dummy",),
    )
    state = {
        "messages": [
            HumanMessage(content="old-1"),
            HumanMessage(content="old-2"),
            HumanMessage(content="old-3"),
            HumanMessage(content="new-1"),
            HumanMessage(content="new-2"),
            HumanMessage(content="new-3"),
            HumanMessage(content="new-4"),  # 第 7 条
        ]
    }
    ctx = mw._extract_user_context(state)
    assert ctx is not None
    # new-1/2/3/4 中只取最近 3 条(new-2/3/4)
    assert "new-1" not in ctx
    assert "new-2" in ctx
    assert "new-3" in ctx
    assert "new-4" in ctx
    assert "old-" not in ctx
