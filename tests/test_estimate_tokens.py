"""测试 _estimate_tokens 的 token 估算 + 上下文占比。

v2(2026-06-28): 改用 :func:`langchain_core.messages.utils.count_tokens_approximately`
作为底层计数器,跟 deepagents 内部 ``_should_summarize`` 用同一套算法。
所以测试不再验证具体系数(中 ×2.5 / 英 ×0.25 / 其他 ×0.5),改为:
  - 接受 str 和 list 两种输入
  - clamp 到 100%
  - 0/负数 context_window 兜底
  - 默认 context_window = 200000
  - 空输入 → 0 tokens
  - 中文长文本产生的 token 数 < 字符数(防止再回到系数高估老路)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nexus.backend.api.ws import _estimate_tokens


class TestEstimateTokensStrInput:
    """str 入口:单段文本(测试 / 降级用)。"""

    def test_empty_text_returns_zero(self) -> None:
        """空文本应返回 0 tokens、0% 占比。"""
        tokens, usage = _estimate_tokens("", context_window=32_000)
        assert tokens == 0
        assert usage == 0.0

    def test_short_chinese_text_undercounted_vs_heuristic(self) -> None:
        """短中文:新计数 < 旧字符系数(防止回退到 2.5× 高估老路)。

        旧启发式:4 字 × 2.5 = 10 tokens。新计数应该明显少(走 chars_per_token=4)。
        这是**回归保护**:若有人偷偷换回字符系数实现,这个断言会挂。
        """
        tokens, _ = _estimate_tokens("你好世界", context_window=32_000)
        # 旧系数会给 10。新计数(<10)说明底层是 langchain 启发式。
        assert tokens < 10, f"token 估算 {tokens} ≥ 10,疑似回退到旧字符系数 2.5×"

    def test_pure_english_text_uses_langchain_approximation(self) -> None:
        """纯英文:100 字符的 token 数应在 25-50 之间(4-2 chars/token)。"""
        tokens, _ = _estimate_tokens("a" * 100, context_window=32_000)
        # count_tokens_approximately default chars_per_token=4,加上 1 条 message
        # 的 extra overhead(~3 tokens),总约 28。给一个宽范围防止边界波动。
        assert 25 <= tokens <= 50, f"100 字符英文估 {tokens} tokens,期望 25-50 (chars_per_token=4 范围)"


class TestEstimateTokensListInput:
    """list 入口(生产场景):累积整个会话 messages。"""

    def test_empty_messages_returns_zero(self) -> None:
        """空 list 返回 0 tokens。"""
        tokens, usage = _estimate_tokens([], context_window=32_000)
        assert tokens == 0
        assert usage == 0.0

    def test_realistic_conversation_returns_reasonable_tokens(self) -> None:
        """5 条典型对话应该返回合理 token 数(不是字符数 × 系数)。"""
        msgs = [
            {"role": "system", "content": ""},
            {"role": "user", "content": "你是谁?"},
            {"role": "assistant", "content": "我是 AI 助手。"},
            {"role": "user", "content": "你跟 GPT-4 有什么区别?"},
            {"role": "assistant", "content": "GPT-4 是 OpenAI 的大模型,我是 MiniMax-M3。"},
        ]
        tokens, usage = _estimate_tokens(msgs, context_window=200_000)
        # 5 条短消息 → 大约 30-60 tokens(5 messages × ~3 overhead + content)。
        # 关键:远小于字符数(总 ~80 字符 × 2.5 = 200 的旧系数值)。
        assert 20 <= tokens <= 100, f"5 条短消息估 {tokens} tokens,期望 20-100"
        # 占 200K 上下文 < 0.1%
        assert usage < 0.1

    def test_long_conversation_does_not_explode(self) -> None:
        """50 轮 × 240 字符中文对话:token 数应 < 字符数(防止旧系数高估)。

        这是核心回归保护:旧系数会给 50×240×2.5 = 30000,新计数应该明显少。
        用户的"89% / 178k/200k"误报就是这种文本规模。
        """
        msgs = []
        for _ in range(50):
            msgs.append({"role": "user", "content": "你" * 240})
            msgs.append({"role": "assistant", "content": "我" * 240})
        tokens, _ = _estimate_tokens(msgs, context_window=200_000)
        # 字符总数 = 50×2×240 = 24000 字符
        # 旧系数:24000 × 2.5 = 60000 tokens
        # 新计数:远小于 60000(走 4 chars/token + per-message overhead)
        assert tokens < 10_000, f"50 轮 × 240 中文字符估 {tokens} tokens,期望 < 10000 (旧系数会给 60000,新计数应明显少)"


class TestContextWindow:
    """context_window 参数与兜底逻辑。"""

    def test_default_context_window_is_200000(self) -> None:
        """不传 context_window 时默认 200000。"""
        text = "a" * 1000
        tokens_default, usage_default = _estimate_tokens(text)
        tokens_explicit, usage_explicit = _estimate_tokens(text, context_window=200_000)
        assert tokens_default == tokens_explicit
        assert usage_default == usage_explicit

    def test_context_window_affects_percentage_only(self) -> None:
        """context_window 只影响 %,不影响 token 数。"""
        text = "a" * 1000
        tokens_8k, usage_8k = _estimate_tokens(text, context_window=8_000)
        tokens_32k, usage_32k = _estimate_tokens(text, context_window=32_000)
        tokens_200k, usage_200k = _estimate_tokens(text, context_window=200_000)
        assert tokens_8k == tokens_32k == tokens_200k
        assert usage_8k > usage_32k > usage_200k

    def test_zero_context_window_falls_back_to_default(self) -> None:
        """context_window=0 兜底到 200000。"""
        text = "a" * 1000
        tokens_zero, usage_zero = _estimate_tokens(text, context_window=0)
        tokens_default, usage_default = _estimate_tokens(text)
        assert tokens_zero == tokens_default
        assert usage_zero == usage_default

    def test_negative_context_window_falls_back_to_default(self) -> None:
        """负数 context_window 也兜底。"""
        text = "a" * 1000
        tokens_neg, usage_neg = _estimate_tokens(text, context_window=-100)
        tokens_default, usage_default = _estimate_tokens(text)
        assert tokens_neg == tokens_default
        assert usage_neg == usage_default

    def test_usage_clamped_to_100(self) -> None:
        """超长文本占比 clamp 到 100,不显示 200% 那种尴尬数字。"""
        huge = "a" * 10_000_000
        _, huge_usage = _estimate_tokens(huge, context_window=200_000)
        assert huge_usage == 100.0


class TestUnderlyingImplementation:
    """验证 _estimate_tokens 真的用了 count_tokens_approximately,不是偷偷
    用了别的实现(防止有人改回字符系数)。"""

    def test_calls_count_tokens_approximately(self) -> None:
        """_estimate_tokens 必须调 count_tokens_approximately。

        用 patch 验证调用链:无论传 str 还是 list,内部都走 langchain。
        """
        with patch(
            "langchain_core.messages.utils.count_tokens_approximately",
            return_value=12345,
        ) as mock_count:
            tokens, usage = _estimate_tokens("hello", context_window=200_000)
            assert mock_count.called, "count_tokens_approximately 必须被调用 — 防止有人改回字符系数"
            assert tokens == 12345
            assert usage == round(12345 / 200_000 * 100, 1)


# WHY fixture:把常用的"50 轮中文对话"模板抽出来,多个测试复用,避免
# 重复 50 行数据。
@pytest.fixture
def long_chinese_conversation() -> list[dict[str, str]]:
    """50 轮 × 240 中文字符的典型长对话,用来回归保护。"""
    msgs: list[dict[str, str]] = []
    for _ in range(50):
        msgs.append({"role": "user", "content": "你" * 240})
        msgs.append({"role": "assistant", "content": "我" * 240})
    return msgs


def test_long_chinese_conversation_realistic_usage(
    long_chinese_conversation: list[dict[str, str]],
) -> None:
    """用户报告的"89% / 178k/200k"误报场景:新计数应该 < 5%。

    WHY:这是触发本次修复的用户实际场景。如果新计数仍然误报 >50%,
    说明 _estimate_tokens 没真正切到 count_tokens_approximately。
    """
    tokens, usage = _estimate_tokens(long_chinese_conversation, context_window=200_000)
    # 字符总数 = 50 × 2 × 240 = 24000 字符
    # 旧系数:24000 × 2.5 = 60000 tokens → 30%
    # 实际 langchain 计数:< 5%(走 4 chars/token + overhead)
    assert usage < 5.0, (
        f"50 轮 × 240 中文字符估 {usage}%,期望 < 5% (旧系数会给 ~30%,新计数应明显少,UI 不应再误报接近 90%)"
    )
