"""identity/directives.py 模板渲染器回归测试。

WHY: FACT 块 + FINAL REMINDER 累积 4 commit 贴片(2026-06-29 ~ 2026-07-01),
字符串内容难追。模板化后,这些测试锁定关键内容存在 + 关键变量被正确替换。"""

from __future__ import annotations

from nexus.backend.identity.directives import (
    DIRECTIVES,
    render_fact_block,
    render_final_reminder,
)


def test_render_fact_block_substitutes_driver() -> None:
    out = render_fact_block("test-driver", "TestVendor")
    assert "test-driver" in out
    assert "TestVendor" in out


def test_render_fact_block_contains_blacklist_from_directives() -> None:
    """FACT 块必须包含 DIRECTIVES.training_bias_blacklist 所有项。"""
    out = render_fact_block("d", "v")
    for entry in DIRECTIVES.training_bias_blacklist:
        assert entry in out, f"blacklist 条目 {entry!r} 未出现在 FACT 块"


def test_render_fact_block_contains_identity_keywords() -> None:
    """FACT 块必须包含 DIRECTIVES 身份关键词(用于触发 LLM 走规则)。"""
    out = render_fact_block("d", "v")
    for kw in DIRECTIVES.identity_keywords_zh:
        assert kw in out, f"ZH 关键词 {kw!r} 未出现在 FACT 块"


def test_render_fact_block_contains_get_model_info_tool_call() -> None:
    """FACT 块必须强制 LLM 先调 get_model_info 工具。"""
    out = render_fact_block("d", "v")
    assert "get_model_info" in out


def test_render_final_reminder_substitutes_driver() -> None:
    out = render_final_reminder("test-driver", "TestVendor")
    assert "test-driver" in out
    assert "TestVendor" in out


def test_render_final_reminder_contains_blacklist_from_directives() -> None:
    out = render_final_reminder("d", "v")
    for entry in DIRECTIVES.training_bias_blacklist:
        assert entry in out, f"blacklist 条目 {entry!r} 未出现在 FINAL REMINDER"


def test_dynamic_identity_uses_render_fact_block() -> None:
    """dynamic_identity._build_fact_block 调用 render_fact_block(模板化后行为)。"""
    import inspect

    from nexus.backend.middleware import dynamic_identity

    src = inspect.getsource(dynamic_identity._build_fact_block)
    assert "render_fact_block" in src, "_build_fact_block 必须走单源 render_fact_block"


def test_dynamic_identity_uses_render_final_reminder() -> None:
    import inspect

    from nexus.backend.middleware import dynamic_identity

    src = inspect.getsource(dynamic_identity._build_final_reminder)
    assert "render_final_reminder" in src, "_build_final_reminder 必须走单源 render_final_reminder"
