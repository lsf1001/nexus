"""单元测试:thinking 块元话语剥离。

WHY 单元测试优先:_strip_thinking_metacommentary 是无 IO 纯函数,边界
多(中英文 / 句中 / 句首 / 段首 / 全 strip 后空字符串),100% 覆盖
保证 emit 阶段不漏 strip 也不误 strip。
"""

from __future__ import annotations

from nexus.backend.api.ws.streaming import _strip_thinking_metacommentary


def test_strip_english_i_should_sentence() -> None:
    """英文 'I should' 句被整句剥离。"""
    thinking = "I should be honest about this limitation. Looking at tools, I don't see image gen."
    out = _strip_thinking_metacommentary(thinking)
    assert "I should" not in out
    assert "Looking at tools" in out  # 真推理保留


def test_strip_english_let_me_sentence() -> None:
    """英文 'Let me' 句被整句剥离。"""
    thinking = "Let me respond honestly and helpfully in Chinese.\nThe user wants a koi image."
    out = _strip_thinking_metacommentary(thinking)
    assert "Let me" not in out
    assert "The user wants" in out


def test_strip_english_i_will_at_start() -> None:
    """行首 'I will' 句被整句剥离。"""
    thinking = "I will acknowledge the limitation first.\nThen offer alternatives."
    out = _strip_thinking_metacommentary(thinking)
    assert "I will" not in out
    assert "Then offer alternatives" in out


def test_strip_chinese_woyinggai() -> None:
    """中文 '我应该' 句被整句剥离。"""
    thinking = "我应该直接、简洁地回答,不要过度铺垫。\n用户想要锦鲤图片。"
    out = _strip_thinking_metacommentary(thinking)
    assert "我应该" not in out
    assert "用户想要" in out


def test_strip_chinese_rangwo() -> None:
    """中文 '让我' 句被整句剥离。"""
    thinking = "让我组织一下语言,先承认不行,再给替代方案。\n实际工具列表如下:"
    out = _strip_thinking_metacommentary(thinking)
    assert "让我" not in out
    assert "实际工具列表如下" in out


def test_preserve_real_reasoning_about_problem() -> None:
    """真问题推理("The user wants…" / "Looking at tools…")不被误伤。"""
    thinking = (
        "The user is asking me to generate a koi image.\n"
        "Looking at my available tools, I don't see any image gen tool.\n"
        "No DALL-E, no Midjourney, no SD."
    )
    out = _strip_thinking_metacommentary(thinking)
    assert out == thinking  # 无元话语 → 原样输出


def test_strip_full_meta_block_returns_empty() -> None:
    """全由元话语组成的 thinking → 整段 strip 为空(emit 阶段整帧 skip)。"""
    thinking = "I should respond honestly. I will acknowledge first. Let me organize the response."
    out = _strip_thinking_metacommentary(thinking)
    assert out == ""


def test_preserve_question_analysis() -> None:
    """'用户问的是什么 / 缺什么 / 走哪条' 类真推理不被剥离。"""
    thinking = "用户问的是图像生成能力。\n缺 DALL-E 这类工具。\n走搜图 / 推荐工具 / SVG 三条路。"
    out = _strip_thinking_metacommentary(thinking)
    assert out == thinking


def test_strip_celue_method_line() -> None:
    """'策略是 / 方法:' / 'Approach:' / 'Strategy:' 独立行整行剥离。"""
    thinking = "策略是: 先承认限制,再给替代方案。\n实际可用工具: file / shell / search。"
    out = _strip_thinking_metacommentary(thinking)
    assert "策略是" not in out
    assert "实际可用工具" in out


def test_collapse_extra_newlines() -> None:
    """多个剥离后产生的连续换行被 normalize 成 2 个。"""
    thinking = "I should be honest.\n\n\nI will do X.\n\n\nThe user wants Y."
    out = _strip_thinking_metacommentary(thinking)
    assert "\n\n\n" not in out  # 3+ 换行被压回
    assert "The user wants Y" in out


def test_empty_input() -> None:
    """空输入 → 空输出(no crash)。"""
    assert _strip_thinking_metacommentary("") == ""
