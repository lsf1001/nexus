"""意图路由器:2026-06-29 重构后改用纯函数正则推断,覆盖 4 类 happy + 兜底。

旧版测的是 LLM-to-LLM 分类(1-shot function calling + 5s 超时),新版
:classify_intent` 改用 :func:`nexus.backend.middleware.force_tool.classify_intent_lightweight`
同步推断,这里覆盖它对各意图类别的映射:

  - ``"identity"`` → ``INTENT_CHITCHAT``
  - ``"knowledge"`` → ``INTENT_KNOWLEDGE``
  - ``"task"`` → ``INTENT_TASK``
  - ``"chitchat"`` / 未匹配 → ``INTENT_CHITCHAT``
"""

from __future__ import annotations

from nexus.backend.intent.router import (
    DEFAULT_INTENT,
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
    classify_intent,
)


def test_classify_task_complex_prompt() -> None:
    """任务类指令("帮我 / 写 / 解释")→ INTENT_TASK。"""
    assert classify_intent("帮我写一个 Python 函数") == INTENT_TASK


def test_classify_knowledge_question() -> None:
    """事实/查询类(投资 / 股票 / 行情)→ INTENT_KNOWLEDGE。

    WHY 选"能买吗 / 会涨吗"做样本:_KNOWLEDGE_PATTERNS 含"买不买|能买|
    会涨|会跌",这些明确走事实检索。避免"Python 是什么?"这类 ``是什么``
    pattern 同时命中 _TASK_PATTERNS 边界。
    """
    assert classify_intent("元力股份 能买吗") == INTENT_KNOWLEDGE
    assert classify_intent("BTC 还会涨吗") == INTENT_KNOWLEDGE
    assert classify_intent("平安保险理赔流程") == INTENT_KNOWLEDGE


def test_classify_chitchat_greeting() -> None:
    """闲聊 / 打招呼 → INTENT_CHITCHAT。"""
    assert classify_intent("你好") == INTENT_CHITCHAT


def test_classify_identity_question_maps_to_chitchat() -> None:
    """身份问答归入 chitchat(不调工具,但要在 DB 标记供统计)。

    WHY:身份问答不应该触发工具调用;落库时记 chitchat 即可,跟产品语义对齐。
    """
    assert classify_intent("你是谁?") == INTENT_CHITCHAT
    assert classify_intent("你用的什么模型?") == INTENT_CHITCHAT


def test_classify_empty_string_falls_back_to_default() -> None:
    """空消息 → DEFAULT_INTENT (chitchat)。"""
    assert classify_intent("") == DEFAULT_INTENT
    assert DEFAULT_INTENT == INTENT_CHITCHAT


def test_classify_unicode_garbage_falls_back_to_default() -> None:
    """无法识别的纯表情 / 噪音 → chitchat 兜底。"""
    assert classify_intent("🤔🤔🤔") == INTENT_CHITCHAT
    assert classify_intent("asdfghjkl") == INTENT_CHITCHAT


def test_classify_never_raises() -> None:
    """任何输入都不能让 classify_intent 抛异常(同步函数,内层 try/except 兜底)。"""
    # None / 数字 / NoneType 等异常输入应被空字符串分支或正则 fallback 兜住
    for bad in [None, 123, [], {}, b"bytes"]:  # type: ignore[list-item]
        result = classify_intent(bad)  # type: ignore[arg-type]
        assert result == INTENT_CHITCHAT
