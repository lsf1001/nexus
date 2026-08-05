"""_build_system_prompt 风格参数 + cache key 维度。"""

from nexus.backend.agent import _system_prompt
from nexus.backend.styles import get_style_directive


def test_build_system_prompt_default_omits_style_section() -> None:
    """style='default' 时,prompt 不应含「回复风格」段。"""
    prompt = _system_prompt._build_system_prompt(model_name="", style="default")
    assert "回复风格" not in prompt


def test_build_system_prompt_concise_appends_directive() -> None:
    prompt = _system_prompt._build_system_prompt(model_name="", style="concise")
    assert "回复风格 · 简洁" in prompt
    assert "寒暄" in prompt


def test_build_system_prompt_professional_appends_directive() -> None:
    prompt = _system_prompt._build_system_prompt(model_name="", style="professional")
    assert "回复风格 · 专业" in prompt
    assert "依据" in prompt


def test_get_system_prompt_signature_accepts_style() -> None:
    """get_system_prompt 必须支持 style 参数(向后兼容默认值)。"""
    _system_prompt.reload_system_prompt()
    p_default = _system_prompt.get_system_prompt(model_name="", style="default")
    p_concise = _system_prompt.get_system_prompt(model_name="", style="concise")
    assert p_default != p_concise
    assert "回复风格 · 简洁" in p_concise


def test_get_system_prompt_caches_per_style() -> None:
    """两次调同 style → 第二次走 cache;不同 style → 不同 cache entry。"""
    _system_prompt.reload_system_prompt()
    p1 = _system_prompt.get_system_prompt(model_name="", style="professional")
    p2 = _system_prompt.get_system_prompt(model_name="", style="professional")
    assert p1 == p2
    # 不同 style 应当产生不同的 cache entry
    _system_prompt.get_system_prompt(model_name="", style="concise")
    assert len(_system_prompt._CACHED_PROMPT) >= 2


def test_reload_clears_all_buckets() -> None:
    """reload_system_prompt() 清整个 _CACHED_PROMPT dict。"""
    _system_prompt.reload_system_prompt()
    _system_prompt.get_system_prompt(model_name="", style="concise")
    _system_prompt.get_system_prompt(model_name="", style="professional")
    assert len(_system_prompt._CACHED_PROMPT) >= 2
    _system_prompt.reload_system_prompt()
    assert _system_prompt._CACHED_PROMPT == {}


def test_get_style_directive_roundtrip() -> None:
    """确保 styles 模块提供的 directive 被 _build_system_prompt 正确使用。"""
    for style in ("default", "concise", "professional"):
        prompt = _system_prompt._build_system_prompt(model_name="", style=style)
        if get_style_directive(style):
            assert get_style_directive(style) in prompt
