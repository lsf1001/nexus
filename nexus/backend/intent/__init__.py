"""意图分类枚举(2026-06-29 重构后,具体分类逻辑见 :mod:`.router`)。"""

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
