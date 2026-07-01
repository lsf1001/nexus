"""单源 DIRECTIVES 单元测试。

WHY: identity 关键词 / 黑名单过去分散在 3 个文件 (force_tool / dynamic_identity /
_system_prompt),新增词要 3 处同步改。本测试锁定单源结构与判定逻辑。"""

from __future__ import annotations

import dataclasses

from nexus.backend.identity.directives import (
    DIRECTIVES,
    IdentityDirectives,
    matches_identity_query,
)


def test_blacklist_is_frozenset() -> None:
    assert isinstance(DIRECTIVES.training_bias_blacklist, frozenset)
    assert "MiniMax-M3" in DIRECTIVES.training_bias_blacklist
    assert "Anthropic" in DIRECTIVES.training_bias_blacklist
    assert "Apollo" in DIRECTIVES.training_bias_blacklist


def test_matches_identity_query_zh() -> None:
    assert matches_identity_query("你是谁")
    assert matches_identity_query("你叫什么")
    assert matches_identity_query("你是哪个 AI")


def test_matches_identity_query_en() -> None:
    assert matches_identity_query("Who are you")
    assert matches_identity_query("current model?")
    assert matches_identity_query("what AI are you")


def test_directives_is_frozen() -> None:
    """IdentityDirectives 必须 frozen,防止运行期被改。"""
    assert dataclasses.is_dataclass(DIRECTIVES)
    assert isinstance(DIRECTIVES, IdentityDirectives)
    assert DIRECTIVES.__dataclass_params__.frozen is True


def test_matches_identity_query_non_match() -> None:
    """普通问题不应命中。"""
    assert not matches_identity_query("你好")
    assert not matches_identity_query("今天天气怎么样")
    assert not matches_identity_query("Hello world")


def test_matches_identity_query_en_case_insensitive() -> None:
    """英文关键词走 lowercase 路径,大小写无关。"""
    assert matches_identity_query("WHO ARE YOU")
    assert matches_identity_query("Current Model")
