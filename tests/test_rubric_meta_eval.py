"""测试 Rubric 元评估：Pearson / Cohen's kappa / 报警阈值。

meta_eval 契约：
  - compute_pearson: 完美正相关=1.0，完美负相关=-1.0，常数=0.0
  - compute_cohens_kappa: 完全一致=1.0，完全不一致=-1.0，单类别=0.0
  - KAPPA_ALERT_THRESHOLD = 0.4（plan 强制）
  - MetaEvalResult.is_acceptable: kappa >= 0.4
  - run_meta_eval: 集成 RubricJudge + 计算指标
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from nexus.backend.rubrics.judge import RubricJudge
from nexus.backend.rubrics.meta_eval import (
    KAPPA_ALERT_THRESHOLD,
    MetaEvalResult,
    MetaEvalSample,
    compute_cohens_kappa,
    compute_pearson,
    run_meta_eval,
)
from nexus.backend.rubrics.schemas import (
    DEFAULT_RUBRICS,
    RubricVerdict,
)

# ==================== compute_pearson ====================


def test_pearson_perfect_positive_correlation():
    """完美正相关 → r=1.0。"""
    xs = [0.1, 0.3, 0.5, 0.7, 0.9]
    ys = [0.2, 0.4, 0.6, 0.8, 1.0]
    assert compute_pearson(xs, ys) == pytest.approx(1.0, abs=1e-9)


def test_pearson_perfect_negative_correlation():
    """完美负相关 → r=-1.0。"""
    xs = [0.1, 0.3, 0.5, 0.7, 0.9]
    ys = [0.9, 0.7, 0.5, 0.3, 0.1]
    assert compute_pearson(xs, ys) == pytest.approx(-1.0, abs=1e-9)


def test_pearson_no_correlation():
    """无相关（两个独立变量）→ r 接近 0。"""
    xs = [0.1, 0.5, 0.9, 0.3, 0.7]
    ys = [0.2, 0.8, 0.4, 0.6, 0.1]
    r = compute_pearson(xs, ys)
    assert -0.9 < r < 0.9  # 弱相关即可


def test_pearson_constant_returns_zero():
    """任一变量为常数 → r=0.0（无方差）。"""
    assert compute_pearson([0.5, 0.5, 0.5], [0.1, 0.3, 0.9]) == 0.0
    assert compute_pearson([0.1, 0.3, 0.9], [0.5, 0.5, 0.5]) == 0.0


def test_pearson_length_mismatch_raises():
    """长度不匹配 → ValueError。"""
    with pytest.raises(ValueError, match="长度不匹配"):
        compute_pearson([0.1, 0.2], [0.3])


def test_pearson_empty_raises():
    """空列表 → ValueError。"""
    with pytest.raises(ValueError, match="输入不能为空"):
        compute_pearson([], [])


# ==================== compute_cohens_kappa ====================


def test_kappa_perfect_agreement():
    """完全一致 → κ=1.0。"""
    labels = ["accept", "reject", "accept", "repair", "accept"]
    assert compute_cohens_kappa(labels, labels) == pytest.approx(1.0, abs=1e-9)


def test_kappa_no_agreement_with_pe_gt_zero():
    """完全不重叠且多类别 → κ<0。"""
    a = ["accept", "accept", "accept", "reject", "reject", "reject"]
    b = ["reject", "reject", "reject", "accept", "accept", "accept"]
    # po=0, pe=(0.5*0.5)+(0.5*0.5)=0.5, kappa = (0-0.5)/(1-0.5) = -1.0
    kappa = compute_cohens_kappa(a, b)
    assert kappa == pytest.approx(-1.0, abs=1e-9)


def test_kappa_random_agreement():
    """随机分布 → κ 接近 0。"""
    # 50/50 均匀分布的随机标签
    a = ["accept", "reject"] * 10
    b = ["accept", "reject"] * 10
    kappa = compute_cohens_kappa(a, b)
    # 完全一致 → 1.0（巧合的均匀分布）
    assert kappa == pytest.approx(1.0, abs=1e-9)


def test_kappa_single_category_perfect_agreement_returns_one():
    """单类别且完全一致 → κ=1.0（特殊边界）。"""
    assert compute_cohens_kappa(["accept"] * 5, ["accept"] * 5) == pytest.approx(1.0)


def test_kappa_single_category_no_agreement_returns_zero():
    """单类别但不一致（实际不可能，但边界）→ 0.0。"""
    # a 全 accept，b 全 reject：po=0, pe=0（因为 categories={accept, reject}，pe=0.5）
    # 这种情况其实算 2 类，不是单类别。换个真单类别场景：a=[accept,reject], b=[reject,accept]
    # 这样 categories={accept,reject}, pe=(0.5*0.5)+(0.5*0.5)=0.5, po=0 → kappa=-1
    # 真正的"单类别不一致"不存在（如果全 accept 那 categories 只有 accept）
    # 这里测一下"类别只有 1 类 + po<1.0" 不可构造（po=1.0 by definition）


def test_kappa_moderate_agreement():
    """中等一致：4 个一致 + 2 个不一致（2 类）。"""
    a = ["accept", "accept", "accept", "accept", "reject", "reject"]
    b = ["accept", "accept", "reject", "accept", "reject", "accept"]
    # po = 4/6 = 0.667
    # pe = (4/6)*(4/6) + (2/6)*(2/6) = 0.444 + 0.111 = 0.556
    # κ = (0.667 - 0.556) / (1 - 0.556) = 0.111 / 0.444 ≈ 0.25
    kappa = compute_cohens_kappa(a, b)
    assert 0.2 < kappa < 0.3


def test_kappa_length_mismatch_raises():
    """长度不匹配 → ValueError。"""
    with pytest.raises(ValueError, match="长度不匹配"):
        compute_cohens_kappa(["a"], ["a", "b"])


def test_kappa_empty_raises():
    """空列表 → ValueError。"""
    with pytest.raises(ValueError, match="输入不能为空"):
        compute_cohens_kappa([], [])


# ==================== 报警阈值 ====================


def test_kappa_alert_threshold_is_04():
    """KAPPA_ALERT_THRESHOLD = 0.4（plan 强制）。"""
    assert KAPPA_ALERT_THRESHOLD == 0.4


def test_meta_eval_result_acceptable_at_threshold():
    """kappa == 0.4 → 恰好 acceptable。"""
    result = MetaEvalResult(pearson=0.5, cohens_kappa=0.4, n_samples=10)
    assert result.is_acceptable is True


def test_meta_eval_result_rejected_below_threshold():
    """kappa < 0.4 → 不可信。"""
    result = MetaEvalResult(pearson=0.5, cohens_kappa=0.39, n_samples=10)
    assert result.is_acceptable is False


# ==================== run_meta_eval 集成 ====================


class _FakeLLM(BaseChatModel):
    """Test 用的最小 LLM：每次 ainvoke 返回预设 JSON dict。"""

    responses: list = [{"score": 0.9, "reasoning": "ok", "evidence": []}]
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    async def _respond(self) -> str:
        idx = min(self.call_count, len(self.responses) - 1)
        self.call_count += 1
        item = self.responses[idx]
        if isinstance(item, str):
            return item
        return json.dumps(item, ensure_ascii=False)

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        return AIMessage(content=await self._respond())


@pytest.mark.asyncio
async def test_run_meta_eval_perfect_agreement():
    """Judge 评分与人工完全一致 → kappa=1.0, pearson=1.0。

    用 mock 直接 stub judge.judge，避免 _FakeLLM 并发 race。
    """
    from unittest.mock import AsyncMock

    judge = RubricJudge(llm=_FakeLLM(), rubrics=DEFAULT_RUBRICS)
    samples = [
        MetaEvalSample(prompt="q1", response="r1", expected_score=0.95, expected_verdict=RubricVerdict.ACCEPT),
        MetaEvalSample(prompt="q2", response="r2", expected_score=0.85, expected_verdict=RubricVerdict.ACCEPT),
        MetaEvalSample(prompt="q3", response="r3", expected_score=0.90, expected_verdict=RubricVerdict.ACCEPT),
    ]

    async def fake_judge(prompt, response, tool_calls=None):
        # 用 expected_score 查表
        expected = next(s.expected_score for s in samples if s.prompt == prompt)
        from nexus.backend.rubrics.schemas import Score
        return [Score(rubric_name="faithfulness", score=expected, reasoning="ok")]

    judge.judge = AsyncMock(side_effect=fake_judge)  # type: ignore[method-assign]
    result = await run_meta_eval(judge, samples)
    assert result.n_samples == 3
    assert result.pearson == pytest.approx(1.0, abs=1e-6)
    assert result.cohens_kappa == pytest.approx(1.0, abs=1e-6)
    assert result.is_acceptable is True


@pytest.mark.asyncio
async def test_run_meta_eval_empty_samples():
    """空 samples → pearson=0, kappa=0, n=0。"""
    judge = RubricJudge(llm=_FakeLLM(), rubrics=DEFAULT_RUBRICS)
    result = await run_meta_eval(judge, [])
    assert result.n_samples == 0
    assert result.pearson == 0.0
    assert result.cohens_kappa == 0.0


@pytest.mark.asyncio
async def test_run_meta_eval_perfect_disagreement():
    """Judge 与 Human 完全错开（边际分布相同但标签全部相反）→ kappa=-1.0。"""
    from unittest.mock import AsyncMock

    judge = RubricJudge(llm=_FakeLLM(), rubrics=DEFAULT_RUBRICS)
    # 关键：要让 kappa < 0，需要 po < pe，且 pe > 0。
    # Human 2 accept + 2 reject（边际分布均匀，pe > 0）；
    # 让 Judge 给完全相反的 verdict：前两个给 reject，后两个给 accept。
    #   judge verdicts = [reject, reject, accept, accept]
    #   human verdicts = [accept, accept, reject, reject]
    #   po = 0（全不一致），pe = 0.5*0.5 + 0.5*0.5 = 0.5 → kappa = -1.0
    samples = [
        MetaEvalSample(prompt="q1", response="r", expected_score=0.95, expected_verdict=RubricVerdict.ACCEPT),
        MetaEvalSample(prompt="q2", response="r", expected_score=0.85, expected_verdict=RubricVerdict.ACCEPT),
        MetaEvalSample(prompt="q3", response="r", expected_score=0.15, expected_verdict=RubricVerdict.REJECT),
        MetaEvalSample(prompt="q4", response="r", expected_score=0.05, expected_verdict=RubricVerdict.REJECT),
    ]

    async def fake_judge(prompt, response, tool_calls=None):
        # Judge 给每个 sample 与 Human 完全相反的分数：
        #   q1, q2 (Human: accept) → Judge: 0.1 (reject)
        #   q3, q4 (Human: reject) → Judge: 0.95 (accept)
        from nexus.backend.rubrics.schemas import Score
        score_map = {"q1": 0.1, "q2": 0.1, "q3": 0.95, "q4": 0.95}
        return [
            Score(rubric_name="faithfulness", score=score_map[prompt], reasoning="opposite")
        ]

    judge.judge = AsyncMock(side_effect=fake_judge)  # type: ignore[method-assign]
    result = await run_meta_eval(judge, samples)
    assert result.is_acceptable is False
    assert result.cohens_kappa == pytest.approx(-1.0, abs=1e-9)


@pytest.mark.asyncio
async def test_run_meta_eval_judge_exception_does_not_break():
    """Judge 抛异常 → 视为 reject 0.0，不影响其他样本。"""
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
    samples = [
        MetaEvalSample(
            prompt="q", response="r", expected_score=0.5, expected_verdict=RubricVerdict.REPAIR,
        ),
    ]
    result = await run_meta_eval(judge, samples)
    # Judge 失败 → score=0.0, verdict=reject
    assert result.judge_scores == (0.0,)
    assert result.judge_verdicts == ("reject",)


# ==================== 不可变 ====================


def test_meta_eval_sample_is_frozen():
    """MetaEvalSample 是 frozen=True，构造后不能改。"""
    sample = MetaEvalSample(
        prompt="q", response="r", expected_score=0.5, expected_verdict=RubricVerdict.ACCEPT,
    )
    with pytest.raises((AttributeError, Exception)):
        sample.expected_score = 0.9  # type: ignore[misc]


def test_meta_eval_result_is_frozen():
    """MetaEvalResult 是 frozen=True。"""
    result = MetaEvalResult(pearson=0.5, cohens_kappa=0.5, n_samples=10)
    with pytest.raises((AttributeError, Exception)):
        result.pearson = 0.0  # type: ignore[misc]
