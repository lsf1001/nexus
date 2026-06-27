"""测试 _estimate_tokens 的字符 → token 换算 + 上下文比例。

`_estimate_tokens` 的字符系数（中文 2.5 / 英文 0.25 / 其他 0.5）和
context_usage = tokens / context_window * 100 是核心契约。
"""

from nexus.backend.api.ws import _estimate_tokens


def test_empty_text():
    """空文本应返回 0 tokens、0% 占比。"""
    tokens, usage = _estimate_tokens("", context_window=32000)
    assert tokens == 0
    assert usage == 0.0


def test_pure_chinese():
    """纯中文：4 字 × 2.5 = 10 tokens。"""
    tokens, usage = _estimate_tokens("你好世界", context_window=32000)
    assert tokens == 10
    # 10 / 32000 * 100 = 0.03125 → round(_, 1) = 0.0
    assert usage == 0.0


def test_pure_english():
    """纯英文：10 字 × 0.25 = 2 tokens。"""
    tokens, usage = _estimate_tokens("helloworld", context_window=32000)
    assert tokens == 2  # 10 * 0.25 = 2.5 → int 截断为 2
    assert usage == 0.0


def test_mixed_chinese_english():
    """混合：中英文。"""
    # "你好 world" → 2 中文字符 + 5 英文字符 + 1 空格
    # 2*2.5 + 5*0.25 + 1*0.5 = 5 + 1.25 + 0.5 = 6.75 → int = 6
    tokens, usage = _estimate_tokens("你好 world", context_window=32000)
    assert tokens == 6
    assert usage == 0.0


def test_long_text_hits_visible_percent():
    """长文本应显示非零占比。"""
    # 1000 个英文字符 → 250 tokens
    # 250 / 32000 * 100 = 0.78 → round(_, 1) = 0.8
    text = "a" * 1000
    tokens, usage = _estimate_tokens(text, context_window=32000)
    assert tokens == 250
    assert usage == 0.8


def test_context_window_affects_percentage():
    """context_window 越小，相同 tokens 下占比越大。"""
    text = "a" * 10000  # 2500 tokens
    tokens_8k, usage_8k = _estimate_tokens(text, context_window=8000)
    tokens_32k, usage_32k = _estimate_tokens(text, context_window=32000)
    tokens_200k, usage_200k = _estimate_tokens(text, context_window=200000)
    assert tokens_8k == tokens_32k == tokens_200k == 2500
    assert usage_8k > usage_32k > usage_200k
    assert usage_8k == 31.2 or usage_8k == 31.3  # 2500/8000*100 = 31.25
    assert usage_32k == 7.8  # 2500/32000*100 = 7.8125 → 7.8
    assert usage_200k == 1.2 or usage_200k == 1.3  # 2500/200000*100 = 1.25


def test_zero_context_window_falls_back_to_default():
    """context_window=0 应触发兜底（用 200000）避免 0 除。"""
    text = "a" * 1000  # 250 tokens
    tokens, usage = _estimate_tokens(text, context_window=0)
    assert tokens == 250
    # 250 / 200000 * 100 = 0.125 → 0.1
    assert usage == 0.1


def test_negative_context_window_falls_back_to_default():
    """负数 context_window 也走兜底。"""
    text = "a" * 1000
    tokens, usage = _estimate_tokens(text, context_window=-100)
    assert tokens == 250
    assert usage == 0.1


def test_max_percent_clamped_to_100():
    """超长文本(tokens > window)占比 clamp 到 100,不被放大。

    三种 window 对照,验证 clamp 在 tokens > window 时生效,
    且不会破坏"tokens > window"以外的正常计算。
    """
    # 1M 字符 × 0.25 = 250K tokens
    text = "a" * 1_000_000
    assert len(text) * 0.25 == 250_000  # 锚定文本规模

    # 1. 默认 200K: 250K > 200K → clamp 100
    tokens_default, usage_default = _estimate_tokens(text)
    assert tokens_default == 250_000
    assert usage_default == 100.0

    # 2. 显式 100K: 250K > 100K → clamp 100
    tokens_100k, usage_100k = _estimate_tokens(text, context_window=100_000)
    assert tokens_100k == 250_000
    assert usage_100k == 100.0

    # 3. 显式 300K: 250K < 300K → 不 clamp,真实占比 83.3%
    tokens_300k, usage_300k = _estimate_tokens(text, context_window=300_000)
    assert tokens_300k == 250_000
    assert usage_300k == 83.3  # 250000/300000*100 = 83.333... → round 1 = 83.3


def test_thinking_tags_ignored_in_estimate():
    """<thinking> 标签本身被 estimated（不剥离）。这是预期：<thinking> 也是字符。"""
    text = "<thinking>用户在问问题</thinking>回答内容"
    tokens, _ = _estimate_tokens(text, context_window=32000)
    # 整体按字符估算（不剥离标签）
    assert tokens > 0


def test_default_context_window_is_200000():
    """不传 context_window 时默认 200000(NEXUS 项目当前假设)。"""
    text = "a" * 1000  # 250 tokens
    tokens_default, usage_default = _estimate_tokens(text)
    tokens_explicit, usage_explicit = _estimate_tokens(text, context_window=200000)
    assert tokens_default == tokens_explicit
    assert usage_default == usage_explicit
