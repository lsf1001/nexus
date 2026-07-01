"""验证 3 个 consumer (force_tool / dynamic_identity / _system_prompt)
都从单源 ``DIRECTIVES`` 派生身份判定 / 黑名单,新增关键词能自动覆盖三者。

WHY: 2026-07-01 之前,关键词 / 黑名单分散在 3 个文件,新增词要 3 处同步改,
     极易漏改导致 consumer 间判定不一致。本测试锁定单源结构,验证 3 个
     consumer 都从 ``DIRECTIVES`` 派生,新增词能自动覆盖三者。
"""

from __future__ import annotations

import inspect

from nexus.backend.identity.directives import DIRECTIVES


def test_force_tool_uses_directives_helper() -> None:
    """force_tool.classify_intent_lightweight 通过 matches_identity_query 判定 identity。"""
    from nexus.backend.middleware import force_tool

    # 'current model' 在 DIRECTIVES.identity_keywords_en 中(新词);
    # 旧 _IDENTITY_PATTERNS 没匹配,新链路应触发
    assert force_tool.classify_intent_lightweight("current model?") == "identity"
    assert force_tool.classify_intent_lightweight("你是谁") == "identity"
    # 普通问句不应触发
    assert force_tool.classify_intent_lightweight("今天天气") == "chitchat"


def test_dynamic_identity_uses_directives_helper() -> None:
    """dynamic_identity._looks_like_identity_question 通过 matches_identity_query 判定。"""
    from nexus.backend.middleware import dynamic_identity

    # '你叫什么名字' 是新加的词,DIRECTIVES 已含,新链路应命中
    assert dynamic_identity._looks_like_identity_question("你叫什么名字")
    assert dynamic_identity._looks_like_identity_question("Who are you")
    assert not dynamic_identity._looks_like_identity_question("你好")


def test_force_tool_no_longer_has_local_identity_patterns() -> None:
    """force_tool 模块不再持有本地 _IDENTITY_PATTERNS 常量(已迁出)。"""
    import nexus.backend.middleware.force_tool as ft

    assert not hasattr(ft, "_IDENTITY_PATTERNS")


def test_dynamic_identity_no_longer_has_local_keywords() -> None:
    """dynamic_identity 模块不再持有本地 _IDENTITY_KEYWORDS_* 常量。"""
    import nexus.backend.middleware.dynamic_identity as di

    assert not hasattr(di, "_IDENTITY_KEYWORDS_ZH")
    assert not hasattr(di, "_IDENTITY_KEYWORDS_EN")


def test_system_prompt_blacklist_uses_directives() -> None:
    """_system_prompt 的 prose 黑名单包含 DIRECTIVES.training_bias_blacklist 所有项。

    三层验证:
      1. 模块导入 DIRECTIVES(防止有人 revert imports)
      2. 模块持有 _TRAINING_BIAS_BLACKLIST_TEXT 拼接常量(防止有人 revert 拼接逻辑)
      3. 拼接结果包含 blacklist 所有条目(防止有人手抄错)
    """
    from nexus.backend.agent import _system_prompt as sp_mod

    src = inspect.getsource(sp_mod)
    assert "DIRECTIVES" in src, "_system_prompt.py 必须 import 单源 DIRECTIVES"

    # Structural: 模块顶层有拼接常量
    assert hasattr(sp_mod, "_TRAINING_BIAS_BLACKLIST_TEXT"), (
        "_system_prompt.py 必须在模块顶层定义 _TRAINING_BIAS_BLACKLIST_TEXT 拼接常量"
    )

    # Behavioral: 拼接结果覆盖 blacklist 所有项
    for entry in DIRECTIVES.training_bias_blacklist:
        assert entry in sp_mod._TRAINING_BIAS_BLACKLIST_TEXT, (
            f"blacklist 条目 {entry!r} 未出现在 _TRAINING_BIAS_BLACKLIST_TEXT"
        )
