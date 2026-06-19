"""意图识别路由:复用主 ChatModel 做 1-shot function-calling 分类。"""

from .router import (
    DEFAULT_INTENT,
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
    IntentKind,
    classify_intent,
)

__all__ = [
    "DEFAULT_INTENT",
    "INTENT_CHITCHAT",
    "INTENT_KNOWLEDGE",
    "INTENT_TASK",
    "IntentKind",
    "classify_intent",
]
