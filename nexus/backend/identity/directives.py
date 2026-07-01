"""单源化 identity / 反训练记忆 黑名单 / FACT 模板。

替代 3 文件 (force_tool.py / dynamic_identity.py / _system_prompt.py) 独立维护的
关键词表、黑名单、禁止句式。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 关键词 (顺序无关,只在意是否命中): force_tool.py 走 regex (用于强插 tool_call),
#                                       dynamic_identity.py 走 substring (用于注入 reminder),
#                                       _system_prompt.py 只写在 prose 里。
# 现统一为 regex + 字符串列表的双视图。
_IDENTITY_KEYWORDS_ZH: tuple[str, ...] = (
    "你是谁",
    "你叫什么",
    "你用的什么模型",
    "你是哪个",
    "用的什么模型",
    "你叫什么名字",
)
_IDENTITY_KEYWORDS_EN: tuple[str, ...] = (
    "who are you",
    "what model",
    "current model",
    "what ai are you",
    "which model",
)

# 训练记忆黑名单:不能答出这些名字 (除 active model)。
# 顺序无意义;新增名字集中在这里,3 个 consumer 都从这里派生。
_TRAINING_BIAS_BLACKLIST: frozenset[str] = frozenset(
    {
        "MiniMax-M3",
        "Claude",
        "Qwen",
        "GPT",
        "Agnes",
        "Sapiens",
        "Anthropic",
        "OpenAI",
        "Apollo",
    }
)


@dataclass(frozen=True)
class IdentityDirectives:
    identity_keywords_zh: tuple[str, ...] = _IDENTITY_KEYWORDS_ZH
    identity_keywords_en: tuple[str, ...] = _IDENTITY_KEYWORDS_EN
    training_bias_blacklist: frozenset[str] = field(default_factory=lambda: _TRAINING_BIAS_BLACKLIST)


DIRECTIVES = IdentityDirectives()


def matches_identity_query(text: str) -> bool:
    """统一身份问题判定 (force_tool / dynamic_identity 共用)。"""
    lowered = text.lower()
    for kw in DIRECTIVES.identity_keywords_zh:
        if kw in text:
            return True
    for kw in DIRECTIVES.identity_keywords_en:
        if kw in lowered:
            return True
    return False
