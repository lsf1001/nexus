"""风格常量 + get_style_directive 单元测试。"""

from nexus.backend.styles import (
    STYLE_DIRECTIVES,
    VALID_STYLES,
    StyleOption,
    get_style_directive,
)


def test_valid_styles_has_three_values() -> None:
    assert VALID_STYLES == ("default", "concise", "professional")


def test_default_directive_is_empty_string() -> None:
    assert STYLE_DIRECTIVES["default"] == ""


def test_concise_directive_mentions_brevity() -> None:
    directive = STYLE_DIRECTIVES["concise"]
    assert "简洁" in directive
    assert "寒暄" in directive


def test_professional_directive_mentions_rigor() -> None:
    directive = STYLE_DIRECTIVES["professional"]
    assert "专业" in directive
    assert "依据" in directive


def test_get_style_directive_default_returns_empty() -> None:
    assert get_style_directive("default") == ""


def test_get_style_directive_concise_returns_directive() -> None:
    assert "简洁" in get_style_directive("concise")


def test_get_style_directive_professional_returns_directive() -> None:
    assert "专业" in get_style_directive("professional")


def test_get_style_directive_unknown_returns_empty() -> None:
    assert get_style_directive("nonexistent") == ""


def test_style_option_is_literal_type() -> None:
    """保证 TypeScript ↔ Python 类型同步：三选一，不容非法值。"""
    valid: tuple[StyleOption, ...] = ("default", "concise", "professional")
    assert VALID_STYLES == valid
