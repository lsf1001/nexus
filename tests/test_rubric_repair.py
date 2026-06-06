"""测试 RepairStrategy：safety 一票否决、repair 次数上限、加权聚合、prompt 生成。

RepairStrategy 契约：
  - safety < 0.5 → REJECT（一票否决）
  - 所有维度 ≥ accept_threshold → ACCEPT
  - 介于 repair / accept 阈值之间 → REPAIR
  - 任一维度 < repair_threshold → REPAIR
  - attempt_count >= max_repair_attempts → 即使触发 repair 也返回 REJECT
  - 加权聚合使用 Rubric.weight
  - repair_prompt 含失败维度名 + 评分员反馈
"""

from __future__ import annotations

import pytest

from nexus.backend.rubrics.repair import RepairStrategy
from nexus.backend.rubrics.schemas import (
    DEFAULT_RUBRICS,
    FAITHFULNESS_RUBRIC,
    RELEVANCE_RUBRIC,
    SAFETY_RUBRIC,
    RubricVerdict,
    Score,
)

# ==================== 工厂函数 ====================


def _score(rubric_name: str, value: float, reasoning: str = "ok") -> Score:
    """构造一个 Score 对象的便捷函数。"""
    return Score(rubric_name=rubric_name, score=value, reasoning=reasoning)


def _scores_for_default(*values: float) -> list[Score]:
    """按 DEFAULT_RUBRICS 顺序构造 Score 列表。"""
    names = [r.name for r in DEFAULT_RUBRICS]
    assert len(values) == len(names), f"期望 {len(names)} 个 score，给了 {len(values)}"
    return [_score(n, v) for n, v in zip(names, values, strict=True)]


# ==================== happy path：全部 ACCEPT ====================


def test_all_scores_above_accept_threshold_returns_accept():
    """4 个维度都 ≥ accept_threshold → ACCEPT。"""
    strategy = RepairStrategy()
    # SAFETY_RUBRIC accept=0.9, 其他 0.8
    scores = _scores_for_default(0.95, 0.9, 0.95, 0.9)
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.ACCEPT
    assert "accept_threshold" in reason or "加权综合分" in reason


# ==================== safety 一票否决 ====================


def test_safety_below_05_returns_reject_veto():
    """safety < 0.5 → REJECT（一票否决），其他维度再高也无效。"""
    strategy = RepairStrategy()
    scores = _scores_for_default(1.0, 1.0, 0.3, 1.0)  # safety=0.3
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REJECT
    assert "safety" in reason.lower()
    assert "0.30" in reason or "0.3" in reason
    assert "一票否决" in reason or "veto" in reason.lower()


def test_safety_veto_disabled_lets_safety_repair_normally():
    """safety_veto=False → safety 0.3 不直接 REJECT，走普通 repair 流程。"""
    strategy = RepairStrategy(safety_veto=False)
    # safety 0.3 < safety.repair_threshold (0.7) → 触发 REPAIR（不 REJECT）
    scores = _scores_for_default(0.95, 0.9, 0.3, 0.9)
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR
    assert "safety" in reason or "未达" in reason or "维度" in reason


def test_safety_above_05_does_not_veto():
    """safety=0.5 → 边界：>= 0.5 不触发 veto（threshold 严格小于）。"""
    strategy = RepairStrategy()
    # safety 0.5 不触发 veto；但 0.5 < safety.repair_threshold (0.7) → REPAIR
    scores = _scores_for_default(0.95, 0.9, 0.5, 0.9)
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR


# ==================== REPAIR 触发 ====================


def test_faithfulness_below_repair_threshold_returns_repair():
    """faithfulness < repair_threshold (0.6) → REPAIR。"""
    strategy = RepairStrategy()
    scores = _scores_for_default(0.5, 0.9, 0.95, 0.9)  # faithfulness=0.5
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR
    assert "faithfulness" in reason


def test_dimension_between_repair_and_accept_returns_repair():
    """维度分介于 repair 和 accept 之间 → REPAIR（保守策略）。"""
    strategy = RepairStrategy()
    # relevance 0.7：repair=0.6 ≤ 0.7 < accept=0.8 → REPAIR
    scores = _scores_for_default(0.95, 0.7, 0.95, 0.9)
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR
    assert "relevance" in reason


def test_multiple_failed_dimensions_all_listed_in_prompt():
    """多个维度失败时，repair_prompt 列出全部。"""
    strategy = RepairStrategy()
    scores = _scores_for_default(0.5, 0.7, 0.95, 0.4)  # faithfulness + tool_correctness fail
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR
    assert "faithfulness" in reason
    assert "tool_correctness" in reason
    # 改进建议部分
    assert "改进" in reason or "要求" in reason


# ==================== repair 次数上限 ====================


def test_attempt_count_at_max_returns_reject_even_if_repair_eligible():
    """attempt_count >= max_repair_attempts → REJECT（plan 强制）。"""
    strategy = RepairStrategy(max_repair_attempts=1)
    scores = _scores_for_default(0.5, 0.9, 0.95, 0.9)  # faithfulness 失败
    # attempt_count=0 → REPAIR
    v0, _ = strategy.decide(scores, DEFAULT_RUBRICS, attempt_count=0)
    assert v0 == RubricVerdict.REPAIR
    # attempt_count=1 → 达到上限，REJECT
    v1, reason1 = strategy.decide(scores, DEFAULT_RUBRICS, attempt_count=1)
    assert v1 == RubricVerdict.REJECT
    assert "上限" in reason1 or "max" in reason1.lower()
    # attempt_count=2 → 仍 REJECT
    v2, _ = strategy.decide(scores, DEFAULT_RUBRICS, attempt_count=2)
    assert v2 == RubricVerdict.REJECT


def test_max_repair_attempts_zero_blocks_repair():
    """max_repair_attempts=0 → 任何 repair 触发都直接 REJECT。"""
    strategy = RepairStrategy(max_repair_attempts=0)
    scores = _scores_for_default(0.5, 0.9, 0.95, 0.9)
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS, attempt_count=0)
    assert verdict == RubricVerdict.REJECT
    assert "上限" in reason


# ==================== 校验 ====================


def test_empty_scores_raises():
    """空 scores 抛 ValueError。"""
    strategy = RepairStrategy()
    with pytest.raises(ValueError, match="不可为空"):
        strategy.decide([], DEFAULT_RUBRICS)


def test_empty_rubrics_raises():
    """空 rubrics 抛 ValueError。"""
    strategy = RepairStrategy()
    scores = [_score("a", 0.9)]
    with pytest.raises(ValueError, match="不可为空"):
        strategy.decide(scores, [])


def test_mismatched_lengths_raises():
    """scores 长度 != rubrics 长度 → ValueError。"""
    strategy = RepairStrategy()
    scores = [_score("a", 0.9), _score("b", 0.9)]
    rubrics = (FAITHFULNESS_RUBRIC,)
    with pytest.raises(ValueError, match="不匹配"):
        strategy.decide(scores, rubrics)


def test_negative_attempt_count_raises():
    """attempt_count < 0 → ValueError。"""
    strategy = RepairStrategy()
    scores = _scores_for_default(0.95, 0.9, 0.95, 0.9)
    with pytest.raises(ValueError, match=">= 0"):
        strategy.decide(scores, DEFAULT_RUBRICS, attempt_count=-1)


def test_init_rejects_negative_max_repair_attempts():
    """max_repair_attempts < 0 在构造期就拒绝。"""
    with pytest.raises(ValueError, match=">= 0"):
        RepairStrategy(max_repair_attempts=-1)


# ==================== 加权聚合 ====================


def test_aggregate_uses_rubric_weights():
    """加权综合分使用 Rubric.weight。

    验证：safety=0.7(w=0.30) + relevance=0.9(w=0.25) + faithfulness=0.9(w=0.35)
    + tool_correctness=0.9(w=0.10) = (0.21+0.225+0.315+0.09)/1.0 = 0.84
    """
    from dataclasses import replace

    # 4 个 rubric 都用，threshold 降到 0.5 便于 accept
    rubrics = tuple(
        replace(r, accept_threshold=0.5, repair_threshold=0.3)
        for r in DEFAULT_RUBRICS
    )
    strategy = RepairStrategy(safety_veto=False)
    scores = _scores_for_default(0.9, 0.9, 0.7, 0.9)  # 顺序: faithful/relevance/safety/tool
    verdict, reason = strategy.decide(scores, rubrics)
    assert verdict == RubricVerdict.ACCEPT
    assert "0.84" in reason


def test_aggregate_normalized_by_total_weight():
    """权重和不为 1.0 时，归一化分母。

    两个 rubric weight=0.5 + 0.5 = 1.0；如果改成 0.3 + 0.7 = 1.0，结果一致。
    """
    from dataclasses import replace

    r1 = replace(SAFETY_RUBRIC, accept_threshold=0.5, repair_threshold=0.3, weight=0.3)
    r2 = replace(RELEVANCE_RUBRIC, accept_threshold=0.5, repair_threshold=0.3, weight=0.7)
    strategy = RepairStrategy(safety_veto=False)
    scores = [_score("safety", 0.7), _score("relevance", 0.9)]
    verdict, _ = strategy.decide(scores, (r1, r2))
    # 0.7*0.3 + 0.9*0.7 = 0.21 + 0.63 = 0.84（与上例同）
    assert verdict == RubricVerdict.ACCEPT


# ==================== repair prompt 内容 ====================


def test_repair_prompt_includes_score_and_reasoning():
    """repair prompt 包含每个失败维度的 score 和 reasoning。"""
    strategy = RepairStrategy()
    scores = [
        _score("faithfulness", 0.5, "提到了不存在的方法"),
        _score("relevance", 0.9, "ok"),
        _score("safety", 0.95, "ok"),
        _score("tool_correctness", 0.9, "ok"),
    ]
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR
    assert "faithfulness" in reason
    assert "0.50" in reason or "0.5" in reason
    assert "提到了不存在的方法" in reason


def test_repair_prompt_evidence_included():
    """repair prompt 包含 evidence（评分员引用的关键句）。"""
    strategy = RepairStrategy()
    scores = [
        Score(
            rubric_name="faithfulness",
            score=0.5,
            reasoning="引用错误",
            evidence=("列表是同步的", "元组是异步的"),
        ),
        _score("relevance", 0.9),
        _score("safety", 0.95),
        _score("tool_correctness", 0.9),
    ]
    verdict, reason = strategy.decide(scores, DEFAULT_RUBRICS)
    assert verdict == RubricVerdict.REPAIR
    assert "列表是同步的" in reason
    assert "元组是异步的" in reason


# ==================== 不可变 ====================


def test_repair_strategy_is_frozen():
    """RepairStrategy 是 frozen=True，构造后不能改字段。"""
    strategy = RepairStrategy()
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
        strategy.safety_veto = False  # type: ignore[misc]
