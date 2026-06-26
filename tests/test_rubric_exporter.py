"""测试 PreferenceExporter：DPO / KTO 格式输出 + score gap 过滤 + CLI 注册。

PreferenceExporter 契约：
  - 接受 PreferenceRecord 列表，输出 jsonl
  - 默认 score gap >= 0.3 才导出
  - DPO 每行 {prompt, chosen, rejected}
  - KTO 每条 record 拆 2 行 {prompt, completion, label: bool}
  - 空 prompt/response 跳过
  - 父目录自动创建
  - CLI 注册函数存在
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.backend.rubrics.exporter import (
    DEFAULT_MIN_SCORE_GAP,
    PreferenceExporter,
    PreferenceRecord,
)

# ==================== 工厂函数 ====================


def _make_record(
    prompt: str = "什么是 Python？",
    accepted: str = "Python 是一种解释型编程语言。",
    accepted_score: float = 0.9,
    rejected: str = "Python 是一种同步的硬件描述语言（错误）。",
    rejected_score: float = 0.2,
    session_id: str = "s1",
    rubric_name: str = "faithfulness",
) -> PreferenceRecord:
    return PreferenceRecord(
        prompt=prompt,
        accepted=accepted,
        accepted_score=accepted_score,
        rejected=rejected,
        rejected_score=rejected_score,
        session_id=session_id,
        rubric_name=rubric_name,
    )


def _make_record_scores(accepted_score: float, rejected_score: float) -> PreferenceRecord:
    """构造一个只用分数指定的 record（参数位置正确）。"""
    return PreferenceRecord(
        prompt="q",
        accepted="a",
        accepted_score=accepted_score,
        rejected="r",
        rejected_score=rejected_score,
    )


# ==================== score gap 过滤 ====================


def test_score_gap_property():
    """PreferenceRecord.score_gap = accepted - rejected。"""
    rec = _make_record(accepted_score=0.9, rejected_score=0.2)
    assert rec.score_gap == pytest.approx(0.7)


def test_passes_gap_default_threshold():
    """score_gap >= 0.3（默认）才通过。"""
    assert _make_record_scores(0.9, 0.2).passes_gap(0.3) is True  # gap=0.7
    assert _make_record_scores(0.5, 0.3).passes_gap(0.3) is False  # gap=0.2
    assert _make_record_scores(0.5, 0.5).passes_gap(0.3) is False  # gap=0


def test_passes_gap_custom_threshold():
    """passes_gap 用传入的阈值。"""
    # gap=0.2 严格大于 0.1，浮点安全
    assert _make_record_scores(0.7, 0.5).passes_gap(0.1) is True
    assert _make_record_scores(0.7, 0.5).passes_gap(0.3) is False


# ==================== DPO 导出 ====================


def test_export_dpo_writes_jsonl_with_prompt_chosen_rejected(tmp_path: Path):
    """DPO 格式：每行 {prompt, chosen, rejected}，空行分隔 JSON。"""
    exporter = PreferenceExporter()
    output = tmp_path / "prefs.jsonl"
    records = [
        _make_record(prompt="q1", accepted="a1", accepted_score=0.9, rejected="r1", rejected_score=0.2),
        _make_record(prompt="q2", accepted="a2", accepted_score=0.85, rejected="r2", rejected_score=0.1),
    ]
    count = exporter.export_dpo(records, output)
    assert count == 2
    lines = output.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for i, line in enumerate(lines):
        data = json.loads(line)
        assert "prompt" in data and "chosen" in data and "rejected" in data
        assert data["prompt"] == f"q{i + 1}"


def test_export_dpo_filters_low_gap(tmp_path: Path):
    """score_gap < 0.3 的 record 不导出。"""
    exporter = PreferenceExporter()
    output = tmp_path / "prefs.jsonl"
    records = [
        _make_record(accepted_score=0.9, rejected_score=0.2),  # gap=0.7 ✓
        _make_record(accepted_score=0.5, rejected_score=0.3),  # gap=0.2 ✗
    ]
    count = exporter.export_dpo(records, output)
    assert count == 1
    lines = output.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


def test_export_dpo_filters_empty_prompt(tmp_path: Path):
    """空 prompt / response 的 record 不导出。"""
    exporter = PreferenceExporter()
    output = tmp_path / "prefs.jsonl"
    records = [
        _make_record(prompt="", accepted="a", rejected="r"),  # 空 prompt ✗
        _make_record(prompt="q", accepted="  ", rejected="r"),  # accepted 全空白 ✗
        _make_record(prompt="q", accepted="a", rejected="\n\t"),  # rejected 全空白 ✗
    ]
    count = exporter.export_dpo(records, output)
    assert count == 0


def test_export_dpo_creates_parent_dirs(tmp_path: Path):
    """输出文件父目录不存在时自动创建。"""
    exporter = PreferenceExporter()
    output = tmp_path / "nested" / "deeper" / "prefs.jsonl"
    assert not output.parent.exists()
    exporter.export_dpo([_make_record()], output)
    assert output.exists()


def test_export_dpo_custom_min_gap(tmp_path: Path):
    """export_dpo 调用时可覆盖 min_score_gap。"""
    exporter = PreferenceExporter(min_score_gap=0.5)  # 默认 0.5
    output = tmp_path / "prefs.jsonl"
    records = [
        _make_record(accepted_score=0.6, rejected_score=0.2),  # gap=0.4 < 0.5
    ]
    # 用 min_gap=0.3 覆盖
    count = exporter.export_dpo(records, output, min_score_gap=0.3)
    assert count == 1


# ==================== KTO 导出 ====================


def test_export_kto_doubles_each_record(tmp_path: Path):
    """KTO 每条 record 拆 2 行：True（accepted）+ False（rejected）。"""
    exporter = PreferenceExporter()
    output = tmp_path / "kto.jsonl"
    records = [
        _make_record(prompt="q", accepted="a", rejected="r"),
    ]
    count = exporter.export_kto(records, output)
    assert count == 2  # 1 record × 2 行
    lines = output.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    d1 = json.loads(lines[0])
    d2 = json.loads(lines[1])
    # 一行 True 一行 False
    assert {d1["label"], d2["label"]} == {True, False}
    # 顺序：先 accepted (True) 后 rejected (False)
    assert d1["label"] is True
    assert d1["completion"] == "a"
    assert d2["label"] is False
    assert d2["completion"] == "r"


def test_export_kto_filters_low_gap(tmp_path: Path):
    """KTO 也走 score gap 过滤。"""
    exporter = PreferenceExporter()
    output = tmp_path / "kto.jsonl"
    records = [
        _make_record(accepted_score=0.5, rejected_score=0.4),  # gap=0.1 ✗
    ]
    count = exporter.export_kto(records, output)
    assert count == 0
    assert output.read_text(encoding="utf-8") == ""


def test_export_kto_prompt_preserved(tmp_path: Path):
    """KTO 每行的 prompt 字段保留原始 prompt。"""
    exporter = PreferenceExporter()
    output = tmp_path / "kto.jsonl"
    records = [
        _make_record(prompt="Python 列表与元组的区别？", accepted="可变 vs 不可变"),
    ]
    exporter.export_kto(records, output)
    for line in output.read_text(encoding="utf-8").strip().split("\n"):
        data = json.loads(line)
        assert data["prompt"] == "Python 列表与元组的区别？"


# ==================== 构造期校验 ====================


def test_default_min_score_gap_is_03():
    """默认 min_score_gap = 0.3（plan 强制）。"""
    assert DEFAULT_MIN_SCORE_GAP == 0.3
    assert PreferenceExporter().min_score_gap == 0.3


def test_invalid_min_score_gap_raises():
    """min_score_gap 越界 → ValueError。"""
    with pytest.raises(ValueError, match=r"min_score_gap 必须在"):
        PreferenceExporter(min_score_gap=1.5)
    with pytest.raises(ValueError, match=r"min_score_gap 必须在"):
        PreferenceExporter(min_score_gap=-0.1)


# ==================== 不可变 ====================


def test_preference_record_is_frozen():
    """PreferenceRecord 是 frozen=True，构造后不能改。"""
    rec = _make_record()
    with pytest.raises((AttributeError, Exception)):
        rec.accepted = "篡改"  # type: ignore[misc]
