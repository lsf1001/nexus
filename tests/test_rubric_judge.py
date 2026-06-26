"""测试 RubricJudge：并发评分、JSON 解析重试、异常隔离、超时、fallback。

RubricJudge 的契约：
  - 4 个内置 rubric → 4 个 Score（顺序与 rubrics 一致）
  - JSON 解析失败重试 N 次
  - 单 rubric 异常不污染其他 rubric
  - 全失败抛 RubricJudgeError
  - 并发执行总耗时 < 串行总和
  - 超时走 fallback，不抛
  - score 自动 clamp 到 [0, 1]
  - 构造时若未传 rubrics，自动 apply_prompts_to_default_rubrics
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind
from nexus.backend.rubrics import prompts as rubric_prompts
from nexus.backend.rubrics import schemas as rubric_schemas
from nexus.backend.rubrics.judge import RubricJudge, RubricJudgeError

# ==================== 测试用 fake LLM ====================


class _FakeLLM(BaseChatModel):
    """测试用假 LLM：基类提供统一 ``ainvoke`` 模板，子类 override ``_respond``。

    行为由构造参数控制：
      - response: dict → 返回 ``json.dumps(response)``
      - response: str → 原样返回
      - response: Exception → 抛出该异常
      - sleep_s: 调用前 sleep 秒数（用于超时 / 并发测试）
      - call_count: 累计调用次数

    模板：``ainvoke`` 自动 ``call_count += 1`` 后调 ``_respond()`` 拿
    文本内容，包成 AIMessage 返回。子类 override ``_respond`` 即可，
    不需要关心 Pydantic 抽象方法和 ``ChatResult.generations`` 路径。
    """

    response: object = {"score": 0.9, "reasoning": "测试默认", "evidence": ["片段"]}
    sleep_s: float = 0.0
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """同步 generate 占位（测试只走 async 路径，但 Pydantic 要求实现）。"""
        raise NotImplementedError("FakeLLM 仅支持 async 调用")

    async def _respond(self) -> str:
        """子类 override：返回 LLM 文本响应，或抛异常。"""
        if self.sleep_s > 0:
            await asyncio.sleep(self.sleep_s)
        if isinstance(self.response, BaseException):
            raise self.response
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response, ensure_ascii=False)

    async def ainvoke(self, input, config=None, stop=None, **kwargs):
        self.call_count += 1
        # 暴露给 _respond 钩子（子类可能要看消息内容做选择性响应）
        if isinstance(input, list):
            self._current_messages = input
        else:
            self._current_messages = [input]
        content = await self._respond()
        return AIMessage(content=content)


def _make_rubrics() -> tuple:
    """构造 4 个轻量 rubric 用于测试（用 dataclass replace 不可变）"""
    from dataclasses import replace

    return tuple(replace(r, prompt=f"[test prompt] {r.name}") for r in rubric_schemas.DEFAULT_RUBRICS)


def _make_judge(llm, rubrics=None, **kwargs) -> RubricJudge:
    """构造 RubricJudge 的便捷函数。"""
    return RubricJudge(llm=llm, rubrics=rubrics or _make_rubrics(), **kwargs)


# ==================== happy path ====================


def test_happy_path_all_4_rubrics():
    """4 个 rubric 全部返回合法 JSON → 4 个 Score，顺序与 rubrics 一致。"""
    llm = _FakeLLM(response={"score": 0.8, "reasoning": "看起来不错", "evidence": ["证据1"]})
    judge = _make_judge(llm)
    scores = asyncio.run(judge.judge(question="什么是 Python？", response="Python 是一种解释型语言。"))
    assert len(scores) == 4
    assert [s.rubric_name for s in scores] == [
        "faithfulness",
        "relevance",
        "safety",
        "tool_correctness",
    ]
    assert all(s.score == 0.8 for s in scores)
    assert all(s.reasoning == "看起来不错" for s in scores)
    # 4 个 rubric 并发调用同一个 llm → 总共 4 次
    assert llm.call_count == 4


# ==================== score clamp ====================


def test_score_clamped_to_unit_interval():
    """LLM 返回 score=1.5 → clamp 到 1.0；返回 -0.3 → clamp 到 0.0。"""
    llm = _FakeLLM(response={"score": 1.5, "reasoning": "满分", "evidence": []})
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1])
    scores = asyncio.run(judge.judge(question="q", response="r"))
    assert scores[0].score == 1.0

    llm2 = _FakeLLM(response={"score": -0.3, "reasoning": "负分", "evidence": []})
    judge2 = _make_judge(llm2, rubrics=_make_rubrics()[:1])
    scores2 = asyncio.run(judge2.judge(question="q", response="r"))
    assert scores2[0].score == 0.0


# ==================== JSON 解析失败重试 ====================


def test_parse_failure_triggers_retry():
    """第一次返回非 JSON、第二次返回合法 JSON → 成功 + 至少调用 2 次。"""
    # 队列模式：第一次返回垃圾，第二次返回合法 JSON
    call_n = [0]

    class _QueueLLM(_FakeLLM):
        async def _respond(self) -> str:
            call_n[0] += 1
            if call_n[0] == 1:
                return "这不是 JSON 啊，哈哈"
            return json.dumps(
                {"score": 0.7, "reasoning": "重试成功", "evidence": []},
                ensure_ascii=False,
            )

    llm = _QueueLLM()
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1], max_parse_retries=2)
    scores = asyncio.run(judge.judge(question="q", response="r"))
    assert scores[0].score == 0.7
    assert "重试成功" in scores[0].reasoning
    # 至少调用 2 次（首次 + 1 次重试）
    assert llm.call_count >= 2


def test_parse_failure_after_retries_yields_fallback_score():
    """一直返回非 JSON → 走 fallback Score（score=0.0，reasoning 含'fallback'）。

    但因为只有 1 个 rubric 且它失败 → 全失败 → 抛 :class:`RubricJudgeError`。
    """
    llm = _FakeLLM(response="永远不是 JSON")
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1], max_parse_retries=1)
    with pytest.raises(RubricJudgeError):
        asyncio.run(judge.judge(question="q", response="r"))
    # 首次 + 1 次重试 = 2 次调用
    assert llm.call_count == 2


def test_parse_failure_yields_fallback_when_other_rubrics_succeed():
    """多个 rubric 时，1 个解析失败不影响其他，且不抛 RubricJudgeError。"""

    class _PartialFailLLM(_FakeLLM):
        async def _respond(self) -> str:
            for m in getattr(self, "_current_messages", []):
                content = str(getattr(m, "content", ""))
                if "[test prompt] relevance" in content:
                    return "这不是 JSON"
            return json.dumps(
                {"score": 0.8, "reasoning": "正常", "evidence": []},
                ensure_ascii=False,
            )

    llm = _PartialFailLLM()
    judge = _make_judge(llm, rubrics=_make_rubrics(), max_parse_retries=1)
    scores = asyncio.run(judge.judge(question="q", response="r"))
    by_name = {s.rubric_name: s for s in scores}
    # relevance 解析失败 → fallback
    assert by_name["relevance"].score == 0.0
    assert "fallback" in by_name["relevance"].reasoning.lower()
    # 其他 3 个正常
    assert by_name["faithfulness"].score == 0.8
    assert by_name["safety"].score == 0.8
    assert by_name["tool_correctness"].score == 0.8


# ==================== 异常隔离 ====================


def test_classified_error_on_one_rubric_does_not_block_others():
    """构造一个仅对特定 rubric name 抛异常的 fake LLM。"""

    class _SelectiveLLM(_FakeLLM):
        async def _respond(self) -> str:
            # 找到当前 rubric name（在 system message 里）
            # 注：ainvoke 不传 messages，要从 input 拿。input 是消息列表
            for m in getattr(self, "_current_messages", []):
                if hasattr(m, "content") and "[test prompt] safety" in str(getattr(m, "content", "")):
                    raise ClassifiedError(
                        kind=LLMErrorKind.RATE_LIMIT,
                        retryable=True,
                        original=Exception("rate limited"),
                        message="[rate_limit] rate limited",
                    )
            return json.dumps(
                {"score": 0.85, "reasoning": "ok", "evidence": []},
                ensure_ascii=False,
            )

    llm = _SelectiveLLM()
    judge = _make_judge(llm)
    scores = asyncio.run(judge.judge(question="q", response="r"))
    assert len(scores) == 4
    # safety 那个位置是 fallback（0.0），其他 3 个是 0.85
    by_name = {s.rubric_name: s.score for s in scores}
    assert by_name["safety"] == 0.0
    assert by_name["faithfulness"] == 0.85
    assert by_name["relevance"] == 0.85
    assert by_name["tool_correctness"] == 0.85


def test_all_rubrics_fail_raises_unavailable():
    """所有 rubric 都抛 ClassifiedError → 抛 RubricJudgeError。"""

    class _AlwaysFailLLM(_FakeLLM):
        async def _respond(self) -> str:
            raise ClassifiedError(
                kind=LLMErrorKind.AUTH,
                retryable=False,
                original=Exception("auth"),
                message="[auth] unauthorized",
            )

    llm = _AlwaysFailLLM()
    judge = _make_judge(llm)
    with pytest.raises(RubricJudgeError):
        asyncio.run(judge.judge(question="q", response="r"))


# ==================== 并发 ====================


def test_concurrent_execution_does_not_block():
    """4 个 rubric 每个 sleep 0.1s，并发总耗时 < 0.3s（串行需要 0.4s）。"""
    llm = _FakeLLM(
        response={"score": 0.5, "reasoning": "ok", "evidence": []},
        sleep_s=0.1,
    )
    judge = _make_judge(llm)
    start = time.monotonic()
    scores = asyncio.run(judge.judge(question="q", response="r"))
    elapsed = time.monotonic() - start
    assert len(scores) == 4
    # 并发：~0.1s；串行：~0.4s。给 0.3s 余量
    assert elapsed < 0.3, f"并发未生效：耗时 {elapsed:.3f}s"


# ==================== 超时 ====================


def test_per_rubric_timeout_yields_fallback_score():
    """单 rubric 的 LLM sleep 1s，per_rubric_timeout=0.1s → 该 rubric 走 fallback。

    4 个 rubric 全超时 → 全 fallback → 抛 :class:`RubricJudgeError`。
    """
    llm = _FakeLLM(
        response={"score": 0.5, "reasoning": "ok", "evidence": []},
        sleep_s=1.0,
    )
    judge = _make_judge(llm, per_rubric_timeout=0.1)
    with pytest.raises(RubricJudgeError):
        asyncio.run(judge.judge(question="q", response="r"))


def test_timeout_on_some_rubrics_yields_partial_fallback():
    """3 个 rubric 超时，1 个正常 → 返回 4 个 Score（3 fallback + 1 正常），不抛。"""

    # 构造一个对 relevance 正常、对其他超时的 LLM
    class _SelectiveTimeoutLLM(_FakeLLM):
        async def _respond(self) -> str:
            for m in getattr(self, "_current_messages", []):
                content = str(getattr(m, "content", ""))
                if "[test prompt] relevance" in content:
                    return json.dumps(
                        {"score": 0.9, "reasoning": "正常", "evidence": []},
                        ensure_ascii=False,
                    )
            await asyncio.sleep(1.0)
            return "won't reach"

    llm = _SelectiveTimeoutLLM()
    judge = _make_judge(llm, per_rubric_timeout=0.1)
    scores = asyncio.run(judge.judge(question="q", response="r"))
    assert len(scores) == 4
    by_name = {s.rubric_name: s for s in scores}
    assert by_name["relevance"].score == 0.9
    assert by_name["faithfulness"].score == 0.0
    assert by_name["safety"].score == 0.0
    assert by_name["tool_correctness"].score == 0.0
    # 不是全失败，不抛 RubricJudgeError
    # （test_all_rubrics_fail_raises_unavailable 验证全失败的场景）


# ==================== 自定义 rubrics + apply prompts ====================


def test_custom_rubrics_respected_not_overridden():
    """传自定义 rubrics → 评估用传入的列表，不依赖 DEFAULT_RUBRICS。"""
    from dataclasses import replace

    custom = (replace(rubric_schemas.FAITHFULNESS_RUBRIC, name="custom_a", prompt="[custom_a]"),)
    llm = _FakeLLM(response={"score": 0.6, "reasoning": "ok", "evidence": []})
    judge = _make_judge(llm, rubrics=custom)
    assert judge.rubrics == custom
    scores = asyncio.run(judge.judge(question="q", response="r"))
    assert len(scores) == 1
    assert scores[0].rubric_name == "custom_a"


def test_apply_prompts_called_on_init():
    """构造 RubricJudge() 不传 rubrics 后，DEFAULT_RUBRICS 的 prompt 字段非空。"""
    # 故意清空 prompt，验证构造时被重新注入
    from dataclasses import replace

    empty_rubrics = tuple(replace(r, prompt="") for r in rubric_schemas.DEFAULT_RUBRICS)
    # 用 monkeypatch：直接覆盖模块的 DEFAULT_RUBRICS 引用
    original = rubric_schemas.DEFAULT_RUBRICS
    try:
        rubric_schemas.DEFAULT_RUBRICS = empty_rubrics  # type: ignore[misc]
        llm = _FakeLLM(response={"score": 0.5, "reasoning": "ok", "evidence": []})
        judge = RubricJudge(llm=llm, rubrics=None)
        # 构造后 judge.rubrics 里每个 prompt 都已注入中文
        assert all(r.prompt != "" for r in judge.rubrics)
        # 且与 prompts 模块里的 prompt 一致
        assert judge.rubrics[0].prompt == rubric_prompts.RUBRIC_PROMPTS[judge.rubrics[0].name]
    finally:
        rubric_schemas.DEFAULT_RUBRICS = original  # type: ignore[misc]


# ==================== 构造期校验 ====================


def test_init_rejects_empty_rubrics():
    """空 rubrics 抛 ValueError。"""
    with pytest.raises(ValueError, match="不能为空"):
        RubricJudge(llm=_FakeLLM(), rubrics=())


def test_init_rejects_negative_parse_retries():
    """max_parse_retries < 0 抛 ValueError。"""
    with pytest.raises(ValueError, match=">= 0"):
        RubricJudge(llm=_FakeLLM(), rubrics=_make_rubrics(), max_parse_retries=-1)


def test_init_rejects_nonpositive_timeout():
    """per_rubric_timeout <= 0 抛 ValueError。"""
    with pytest.raises(ValueError, match=r"必须 > 0"):
        RubricJudge(llm=_FakeLLM(), rubrics=_make_rubrics(), per_rubric_timeout=0)


# ==================== 工具调用透传 ====================


def test_tool_calls_formatted_in_prompt():
    """tool_calls 出现在 user 消息中（验证格式化逻辑）。"""

    captured: list[list] = []

    class _CaptureLLM(_FakeLLM):
        async def _respond(self) -> str:
            captured.append(list(getattr(self, "_current_messages", [])))
            return json.dumps(
                {"score": 0.5, "reasoning": "ok", "evidence": []},
                ensure_ascii=False,
            )

    tool_calls = [
        {"name": "web_search", "args": {"q": "天气"}, "result": "晴天 25度"},
    ]
    llm = _CaptureLLM()
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1])
    asyncio.run(judge.judge(question="北京天气", response="晴天", tool_calls=tool_calls))
    # captured[0] 的 user 消息里应包含工具名 + 参数 + 结果
    all_content = " ".join(str(getattr(m, "content", "")) for m in captured[0])
    assert "web_search" in all_content
    assert "天气" in all_content
    assert "晴天 25度" in all_content


# ==================== callback 隔离(防止 Judge 输出泄漏到主 LLM 的 stream 帧)====================
#
# 根因(bug #58):``RubricJudge._evaluate_one`` 直接 ``self._llm.ainvoke(messages)``
# 不传 config 时,Judge LLM 调用的 ``on_chat_model_stream`` 事件会通过 langgraph
# ``astream_events`` 的 event_streamer 冒泡,被 ws.py 当成"主 LLM 的输出 chunk"
# 累加到 ``full_response``,用户在前端 chunk/final 帧看到 raw JSON(``{"score": 1.0, "reasoning": ...}``)。
# 修复:显式传 ``config={"callbacks": [], "run_name": "rubric_judge.<name>"}`` —— 空
# callbacks list 不继承外层 event_streamer,Judge 输出不再冒泡;run_name 让 langsmith
# tracing 能区分 Judge vs 主 LLM 调用。
#
# 这两个测试必须断言:
#  1. ``self._llm.ainvoke`` 收到的 ``config["callbacks"]`` 是空 list(不是 None 也不是
#     默认管理器)
#  2. ``config["run_name"]`` 含 "rubric_judge." 前缀,便于排查/观测


class _CaptureConfigLLM(_FakeLLM):
    """把每次 ``ainvoke`` 收到的 ``config`` dict 收集到 ``captured_configs`` 列表。"""

    captured_configs: list = []

    async def ainvoke(self, input, config=None, stop=None, **kwargs):
        # 抄一份防止下游被改写
        self.captured_configs.append(dict(config) if isinstance(config, dict) else config)
        return await super().ainvoke(input, config=config, stop=stop, **kwargs)


def test_evaluate_one_passes_empty_callbacks():
    """``callbacks=[]`` 隔离:不让 Judge LLM 的 on_* 事件冒泡到外层 astream_events。"""

    class _OneRubricLLM(_CaptureConfigLLM):
        captured_configs: list = []

    llm = _OneRubricLLM(response={"score": 0.9, "reasoning": "ok", "evidence": []})
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1])
    asyncio.run(judge.judge(question="q", response="r"))

    # 至少调一次
    assert len(llm.captured_configs) >= 1
    cfg = llm.captured_configs[0]
    assert isinstance(cfg, dict), f"ainvoke 必须收到 dict config, 实际 {type(cfg).__name__}"
    # 关键断言:callbacks 必须是空 list,不能是 None(继承)也不能是 BaseCallbackManager
    assert "callbacks" in cfg, f"config 必须显式包含 callbacks 键: {cfg}"
    assert cfg["callbacks"] == [], f"callbacks 必须是 [] 阻断传播, 实际 {cfg['callbacks']!r}"


def test_evaluate_one_sets_run_name():
    """``run_name`` 含 ``rubric_judge.`` 前缀:langsmith tracing 能区分 Judge 调用。"""

    class _OneRubricLLM(_CaptureConfigLLM):
        captured_configs: list = []

    llm = _OneRubricLLM(response={"score": 0.9, "reasoning": "ok", "evidence": []})
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1])
    asyncio.run(judge.judge(question="q", response="r"))

    assert len(llm.captured_configs) >= 1
    cfg = llm.captured_configs[0]
    assert cfg.get("run_name", "").startswith("rubric_judge."), (
        f"run_name 应以 'rubric_judge.' 开头, 实际 {cfg.get('run_name')!r}"
    )


def test_evaluate_one_run_name_contains_rubric():
    """``run_name`` 形如 ``rubric_judge.<rubric_name>``:便于按 rubric 维度排查。"""

    class _OneRubricLLM(_CaptureConfigLLM):
        captured_configs: list = []

    llm = _OneRubricLLM(response={"score": 0.9, "reasoning": "ok", "evidence": []})
    # 用单 rubric,验证 run_name 包含 rubric name
    judge = _make_judge(llm, rubrics=_make_rubrics()[:1])
    asyncio.run(judge.judge(question="q", response="r"))

    cfg = llm.captured_configs[0]
    first_rubric_name = _make_rubrics()[0].name
    assert first_rubric_name in cfg["run_name"], (
        f"run_name 应含 rubric 名 '{first_rubric_name}', 实际 {cfg['run_name']!r}"
    )
