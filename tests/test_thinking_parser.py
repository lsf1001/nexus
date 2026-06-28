"""单元测试:ThinkingParser 流式识别 <thinking> 标签。

WHY 单元测试优先:parser 是纯逻辑(无 IO),必须 100% 覆盖边界
(标签分片、嵌套、空标签、<think> 与 <thinking> 混用),
parser 错就全链路错,这是 streaming 修复的根基。
"""

from __future__ import annotations

from nexus.backend.api.thinking_parser import ThinkingParser


def test_plain_response_no_tags() -> None:
    """纯回复(无 thinking 标签)→ 全部按 chunk 发出。"""
    p = ThinkingParser()
    out = p.feed("你好世界")
    assert out == [("chunk", "你好世界")]


def test_full_thinking_block() -> None:
    """完整 <thinking>...</thinking> 块 → 一次 thinking 帧。"""
    p = ThinkingParser()
    out = p.feed("<thinking>分析中</thinking>答案")
    assert out == [("thinking", "分析中"), ("chunk", "答案")]


def test_tag_split_across_chunks() -> None:
    """标签跨 chunk 分片 → 必须正确识别,不能漏。"""
    p = ThinkingParser()
    out1 = p.feed("<think")
    assert out1 == []
    out2 = p.feed("ing>推理过程</think")
    assert out2 == [("thinking", "推理过程")]
    out3 = p.feed("ing>结果")
    assert out3 == [("chunk", "结果")]


def test_think_alt_normalized() -> None:
    """<think> (Anthropic) 与 <thinking> 视为同义,统一归一。"""
    p = ThinkingParser()
    out = p.feed("<think>x</think>y")
    assert out == [("thinking", "x"), ("chunk", "y")]


def test_multiple_thinking_blocks() -> None:
    """多个 thinking 块 → 多次 thinking 帧。"""
    p = ThinkingParser()
    out = p.feed("<thinking>a</thinking>中<thinking>b</thinking>末")
    assert out == [("thinking", "a"), ("chunk", "中"), ("thinking", "b"), ("chunk", "末")]


def test_partial_tag_at_flush_emitted_as_chunk() -> None:
    """流末未闭合的标签 → 当成普通 chunk 发出,不丢。"""
    p = ThinkingParser()
    p.feed("先<thin")
    out = p.flush()
    assert out == [("chunk", "先<thin")]


def test_unclosed_thinking_emitted_at_flush() -> None:
    """开了 thinking 但流末没闭合 → flush 时把累积内容当 thinking 帧发。"""
    p = ThinkingParser()
    p.feed("<thinking>推理过程")
    out = p.flush()
    assert out == [("thinking", "推理过程")]
