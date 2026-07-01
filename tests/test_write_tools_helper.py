"""write_tools helper 单元测试。

WHY: 之前 quality/middleware.py + middleware/hitl.py 各持一份 _FILE_TOOLS /
_WRITE_TOOL_PATTERNS / _READ_ONLY_TOOLS / _is_write_tool —— 典型 copy-paste
反模式。helper 抽出来后,本测试锁定其语义,防止后续重构漂移。"""

from __future__ import annotations


def test_file_tools_is_frozenset() -> None:
    """FILE_TOOLS 必须是 frozenset(不可变),防止运行时被改坏。"""
    from nexus.backend.permissions.write_tools import FILE_TOOLS

    assert isinstance(FILE_TOOLS, frozenset)
    assert "edit_file" in FILE_TOOLS
    assert "write_file" in FILE_TOOLS


def test_write_tool_patterns_is_tuple_of_str() -> None:
    """WRITE_TOOL_PATTERNS 必须是 tuple[str, ...](不可变 + 子串匹配)。"""
    from nexus.backend.permissions.write_tools import WRITE_TOOL_PATTERNS

    assert isinstance(WRITE_TOOL_PATTERNS, tuple)
    assert all(isinstance(p, str) for p in WRITE_TOOL_PATTERNS)
    assert "_file" in WRITE_TOOL_PATTERNS


def test_read_only_tools_is_frozenset() -> None:
    """READ_ONLY_TOOLS 是 frozenset,read_file 必须在内。"""
    from nexus.backend.permissions.write_tools import READ_ONLY_TOOLS

    assert isinstance(READ_ONLY_TOOLS, frozenset)
    assert "read_file" in READ_ONLY_TOOLS


def test_is_write_tool_empty_returns_false() -> None:
    """空名 → False,不抛异常。"""
    from nexus.backend.permissions.write_tools import is_write_tool

    assert is_write_tool("") is False


def test_is_write_tool_known_write_returns_true() -> None:
    """FILE_TOOLS 白名单内的工具 → True。"""
    from nexus.backend.permissions.write_tools import is_write_tool

    assert is_write_tool("edit_file") is True
    assert is_write_tool("write_file") is True
    assert is_write_tool("create_file") is True
    assert is_write_tool("apply_patch") is True
    assert is_write_tool("str_replace_editor") is True


def test_is_write_tool_known_read_returns_false() -> None:
    """READ_ONLY_TOOLS 白名单内的工具 → False(即使含 _file 子串)。"""
    from nexus.backend.permissions.write_tools import is_write_tool

    assert is_write_tool("read_file") is False
    assert is_write_tool("ls") is False
    assert is_write_tool("grep") is False


def test_is_write_tool_unknown_name_with_file_suffix() -> None:
    """未知工具名但以 _file 结尾 → True(substring _file 兜底)。"""
    from nexus.backend.permissions.write_tools import is_write_tool

    assert is_write_tool("modify_file") is True
    assert is_write_tool("save_file") is True


def test_is_write_tool_case_insensitive() -> None:
    """大小写不敏感:tool_name.lower() 后匹配 patterns。

    重要行为细节:
      - ``FILE_TOOLS`` 走**精确匹配**(不区分大小写),``"EDIT_FILE"`` 不命中
        大写白名单 → 进入 fallback → 小写化后命中 ``"edit_"`` 模式 → True
      - ``READ_ONLY_TOOLS`` 也只走小写精确匹配,``"READ_FILE"`` 小写后命中
        → False
    """
    from nexus.backend.permissions.write_tools import is_write_tool

    # 大写 READ_FILE → 小写后命中 READ_ONLY_TOOLS(精确)→ False
    assert is_write_tool("READ_FILE") is False
    # 大写 EDIT_FILE → 不命中 FILE_TOOLS(精确)→ 小写后命中 "edit_" 模式 → True
    assert is_write_tool("EDIT_FILE") is True
    # 混合大小写 Edit_File → 小写后含 "_file" 子串 → True
    assert is_write_tool("Edit_File") is True


def test_is_write_tool_unknown_unrelated_returns_false() -> None:
    """既不在白名单也不命中子串 → False。"""
    from nexus.backend.permissions.write_tools import is_write_tool

    assert is_write_tool("yandex_search") is False
    assert is_write_tool("ask_user") is False


def test_quality_middleware_imports_helper() -> None:
    """QualityGate 中间件必须用 helper(去掉本地 _is_write_tool 定义)。"""
    import inspect

    from nexus.backend.quality import middleware as qm

    # 不能再有本地 _is_write_tool 定义
    assert not hasattr(qm, "_is_write_tool"), "QualityGate 仍持有本地 _is_write_tool,未抽到 permissions.write_tools"
    # 应该有 helper import
    src = inspect.getsource(qm)
    assert "from ..permissions.write_tools import" in src, "QualityGate 未引用 permissions.write_tools"


def test_hitl_middleware_imports_helper() -> None:
    """PathAwareHITL 中间件必须用 helper。"""
    import inspect

    from nexus.backend.middleware import hitl

    assert not hasattr(hitl, "_is_write_tool"), "PathAwareHITL 仍持有本地 _is_write_tool,未抽到 permissions.write_tools"
    src = inspect.getsource(hitl)
    assert "from ..permissions.write_tools import" in src, "PathAwareHITL 未引用 permissions.write_tools"
