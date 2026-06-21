"""Phase 2 Task 2.1: Rubric 数据结构单元测试。

覆盖：
  - RubricVerdict.from_score 工厂方法（ACCEPT / REPAIR / REJECT 三档）
  - Rubric dataclass 字段与冻结语义
  - Rubric 构造期校验（空 name / 越界 weight / 阈值倒挂）
  - Score dataclass 字段与 score 范围校验
  - 内置 4 个 Rubric（faithfulness / relevance / safety / tool_correctness）
  - RubricVerdictResult 加权聚合

不依赖 LLM / LangChain / DB：schemas 是纯数据层。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from nexus.backend.rubrics.schemas import (
    DEFAULT_RUBRICS,
    FAITHFULNESS_RUBRIC,
    RELEVANCE_RUBRIC,
    SAFETY_RUBRIC,
    TOOL_CORRECTNESS_RUBRIC,
    Rubric,
    RubricVerdict,
    RubricVerdictResult,
    Score,
)

# ====== RubricVerdict.from_score ======


def test_verdict_from_score_accept():
    """score >= accept_threshold -> ACCEPT（含边界）。"""
    assert RubricVerdict.from_score(0.95) == RubricVerdict.ACCEPT
    assert RubricVerdict.from_score(0.8, threshold_accept=0.8) == RubricVerdict.ACCEPT
    assert RubricVerdict.from_score(1.0) == RubricVerdict.ACCEPT


def test_verdict_from_score_repair():
    """repair_threshold <= score < accept_threshold -> REPAIR（含边界）。"""
    assert RubricVerdict.from_score(0.7, threshold_accept=0.8, threshold_repair=0.6) == RubricVerdict.REPAIR
    assert RubricVerdict.from_score(0.6, threshold_accept=0.8, threshold_repair=0.6) == RubricVerdict.REPAIR


def test_verdict_from_score_reject():
    """score < repair_threshold -> REJECT。"""
    assert RubricVerdict.from_score(0.5, threshold_accept=0.8, threshold_repair=0.6) == RubricVerdict.REJECT
    assert RubricVerdict.from_score(0.0, threshold_accept=0.8, threshold_repair=0.6) == RubricVerdict.REJECT


def test_verdict_from_score_custom_thresholds():
    """自定义阈值仍然按"高到低"层级判定。"""
    # accept=0.9, repair=0.7
    assert RubricVerdict.from_score(0.95, threshold_accept=0.9, threshold_repair=0.7) == RubricVerdict.ACCEPT
    assert RubricVerdict.from_score(0.8, threshold_accept=0.9, threshold_repair=0.7) == RubricVerdict.REPAIR
    assert RubricVerdict.from_score(0.5, threshold_accept=0.9, threshold_repair=0.7) == RubricVerdict.REJECT


# ====== Rubric dataclass ======


def test_rubric_valid_creation():
    """合法参数下能成功构造，并保留所有字段。"""
    r = Rubric(
        name="test",
        weight=0.5,
        prompt="...",
        accept_threshold=0.8,
        repair_threshold=0.6,
    )
    assert r.name == "test"
    assert r.weight == 0.5
    assert r.prompt == "..."
    assert r.accept_threshold == 0.8
    assert r.repair_threshold == 0.6


def test_rubric_is_frozen():
    """frozen=True：实例字段不可写。"""
    r = Rubric(
        name="test",
        weight=0.5,
        prompt="",
        accept_threshold=0.8,
        repair_threshold=0.6,
    )
    with pytest.raises(FrozenInstanceError):
        r.name = "changed"  # type: ignore[misc]


def test_rubric_rejects_empty_name():
    """name 为空字符串时抛 ValueError。"""
    with pytest.raises(ValueError, match="name"):
        Rubric(
            name="",
            weight=0.5,
            prompt="p",
            accept_threshold=0.8,
            repair_threshold=0.6,
        )


def test_rubric_rejects_invalid_weight():
    """weight 必须在 [0, 1] 区间。"""
    with pytest.raises(ValueError, match="weight"):
        Rubric(
            name="x",
            weight=1.5,
            prompt="p",
            accept_threshold=0.8,
            repair_threshold=0.6,
        )
    with pytest.raises(ValueError, match="weight"):
        Rubric(
            name="x",
            weight=-0.1,
            prompt="p",
            accept_threshold=0.8,
            repair_threshold=0.6,
        )


def test_rubric_rejects_threshold_inversion():
    """repair_threshold > accept_threshold 不合法。"""
    with pytest.raises(ValueError, match="threshold"):
        Rubric(
            name="x",
            weight=0.5,
            prompt="p",
            accept_threshold=0.6,
            repair_threshold=0.8,
        )


# ====== Score dataclass ======


def test_score_valid_creation():
    """合法参数下能成功构造，evidence 自动转 tuple。"""
    s = Score(
        rubric_name="faithfulness",
        score=0.85,
        reasoning="ok",
        evidence=("quote1", "quote2"),
    )
    assert s.rubric_name == "faithfulness"
    assert s.score == 0.85
    assert s.reasoning == "ok"
    assert s.evidence == ("quote1", "quote2")


def test_score_default_evidence_is_empty_tuple():
    """evidence 默认值为空 tuple。"""
    s = Score(rubric_name="relevance", score=0.5, reasoning="x")
    assert s.evidence == ()


def test_score_rejects_out_of_range():
    """score 必须在 [0, 1] 区间。"""
    with pytest.raises(ValueError, match="score"):
        Score(rubric_name="x", score=1.5, reasoning="")
    with pytest.raises(ValueError, match="score"):
        Score(rubric_name="x", score=-0.1, reasoning="")


# ====== 内置 4 个 Rubric ======


def test_default_rubrics_has_four():
    """DEFAULT_RUBRICS 恰好 4 个，且名字集合匹配。"""
    assert len(DEFAULT_RUBRICS) == 4
    names = {r.name for r in DEFAULT_RUBRICS}
    assert names == {"faithfulness", "relevance", "safety", "tool_correctness"}


def test_default_rubrics_thresholds_valid():
    """内置 Rubric 的阈值与权重都满足不变量。"""
    for r in DEFAULT_RUBRICS:
        assert 0.0 <= r.repair_threshold <= r.accept_threshold <= 1.0
        assert 0.0 <= r.weight <= 1.0


def test_safety_threshold_strict():
    """安全 Rubric 的 accept 阈值应 >= 0.9（更严格，避免放行不安全输出）。"""
    assert SAFETY_RUBRIC.accept_threshold >= 0.9


def test_default_rubric_prompts_empty_for_task22():
    """4 个内置 Rubric 的 prompt 暂留空字符串，由 Task 2.2 填充。"""
    for r in DEFAULT_RUBRICS:
        assert r.prompt == ""


# ====== RubricVerdictResult 聚合 ======


def test_verdict_result_aggregate_score():
    """aggregate_score 是各 Score 的算术平均（权重聚合留给上层）。"""
    scores = (
        Score(rubric_name="faithfulness", score=1.0, reasoning=""),
        Score(rubric_name="relevance", score=0.5, reasoning=""),
    )
    result = RubricVerdictResult(verdict=RubricVerdict.ACCEPT, scores=scores)
    assert result.aggregate_score == pytest.approx(0.75)


def test_verdict_result_empty_scores_aggregate_is_zero():
    """无 scores 时 aggregate_score 为 0.0（避免除零）。"""
    result = RubricVerdictResult(verdict=RubricVerdict.REJECT, scores=())
    assert result.aggregate_score == 0.0


def test_verdict_result_preserves_verdict_and_reasoning():
    """verdict 与 reasoning 字段可正常读写。"""
    scores = (Score(rubric_name="safety", score=0.2, reasoning="bad"),)
    result = RubricVerdictResult(
        verdict=RubricVerdict.REJECT,
        scores=scores,
        reasoning="safety 不达标",
    )
    assert result.verdict == RubricVerdict.REJECT
    assert result.reasoning == "safety 不达标"


# ====== 交叉引用一致性 ======


def test_builtin_ruoric_aliases_match_default_list():
    """FAITHFULNESS_RUBRIC / RELEVANCE_RUBRIC / SAFETY_RUBRIC / TOOL_CORRECTNESS_RUBRIC
    都能在 DEFAULT_RUBRICS 中按 name 找到。"""
    aliases = {
        FAITHFULNESS_RUBRIC,
        RELEVANCE_RUBRIC,
        SAFETY_RUBRIC,
        TOOL_CORRECTNESS_RUBRIC,
    }
    assert aliases == set(DEFAULT_RUBRICS)
