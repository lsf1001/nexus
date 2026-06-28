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


def test_stray_close_tag_in_chunk_drops_close_and_keeps_text() -> None:
    """</thinking> 在 chunk 状态出现无意义,前缀和 close 一起被丢弃。

    合同:游离 close 标签(无对应 open)整段连同前缀一并丢弃,
    残留 tail 继续作为 chunk 解析。这是保守策略 — 防止"前缀中恰好
    含有用户可见的恶意 close 标签"导致误切。
    """
    p = ThinkingParser()
    out = p.feed("hello</thinking>world")
    assert out == [("chunk", "world")]


def test_empty_thinking_block_emits_no_thinking_frame() -> None:
    """空标签 <thinking></thinking> 不应产生 thinking 帧(无内容,close 收尾后无 chunk 前缀)。"""
    p = ThinkingParser()
    out = p.feed("<thinking></thinking>")
    assert out == []


def test_nested_thinking_closes_at_first_close_tag() -> None:
    """嵌套 thinking: 在第一个 </thinking> 处关闭,残余文本走 chunk。

    合同:parser 不识别真正的嵌套 — 第一个 close 关闭 thinking 块,
    余下 `<thinking>b</thinking>c</thinking>` 走 chunk 状态解析:
    第二个 `<thinking>` 进入 thinking 块,第二个 `</thinking>` 关闭 thinking,
    第三个 `</thinking>` 视为游离,前缀 "c" 丢弃,只剩空输出。
    """
    p = ThinkingParser()
    out = p.feed("<thinking>a<thinking>b</thinking>c</thinking>")
    # 第一个 </thinking> 关闭外层:thinking = "a<thinking>b"
    # 剩余 "c</thinking>" 在 chunk 状态:close 视为游离,前缀 "c" 也丢弃
    assert out == [("thinking", "a<thinking>b")]
