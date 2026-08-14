"""write_tools helper 单元测试。

WHY: 之前 quality/middleware.py + middleware/hitl.py 各持一份 _FILE_TOOLS /
_WRITE_TOOL_PATTERNS / _READ_ONLY_TOOLS / _is_write_tool —— 典型 copy-paste
反模式。helper 抽出来后,本测试锁定其语义,防止后续重构漂移。"""

from __future__ import annotations


class _StubFilter:
    """最小可用 Filter,只为满足 QualityGateMiddleware 构造约束。"""

    async def check(self, value, user_context=None):  # noqa: ARG002
        from nexus.backend.quality.memory_filter import FilterDecision

        return FilterDecision(allow=True, score=1.0, reason="ok")


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
    assert is_write_tool("delete") is True
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


def test_is_write_tool_delete_file_returns_true() -> None:
    """deepagents 0.7 引入文件删除工具,HITL 必须识别为写工具。

    0.7.4 实测 ``FilesystemMiddleware._FS_TOOL_ORDER`` = ``("ls","read_file",
    "write_file","edit_file","delete","glob","grep")`` — 工具注册的 ``name``
    是字面 ``"delete"``(不是 ``"delete_file"``)。HITL/QualityGate 必须能
    识别两种形式:

      - ``delete``(0.7.4 当前)→ ``FILE_TOOLS`` 精确白名单命中 → True
      - ``delete_file`` / ``remove_file``(未来若改名)→ ``WRITE_TOOL_PATTERNS``
        的 ``"_file"`` 兜底模式 → True

    这是 0.6.12 → 0.7.4 升级的核心 HITL 合约。一旦有人把 ``"delete"`` 从
    白名单移除 / 改名,这个 case 会 RED → LLM 删除项目源码不再触发 HITL,
    静默破坏安全护栏。
    """
    from nexus.backend.permissions.write_tools import is_write_tool

    # 0.7.4 当前字面工具名
    assert is_write_tool("delete") is True
    # 未来若 deepagents 改名为 delete_file,_file 子串模式兜底
    assert is_write_tool("delete_file") is True
    assert is_write_tool("remove_file") is True
    assert is_write_tool("trash_file") is True


def test_is_write_tool_delete_directory_returns_false() -> None:
    """已知 gap:``delete_directory`` 没有 ``_file`` 后缀 → 不被当前 patterns 命中。

    0.7 暂未引入 ``delete_directory``(只引入 ``delete_file``)。若未来
    框架新增 ``delete_directory``,需要在 ``WRITE_TOOL_PATTERNS`` 补
    ``"_dir"`` 或 ``"_directory"``,或加精确白名单条目。本 case 用于
    在补完之前提前 RED,提醒升级时盯 framework 工具集变更。
    """
    from nexus.backend.permissions.write_tools import is_write_tool

    assert is_write_tool("delete_directory") is False


def test_quality_middleware_invokes_helper_for_write_tool(tmp_path) -> None:
    """QualityGate._is_protected 调用 is_write_tool(edit_file → 命中)。

    WHY: Task 7.3 同款 fragility 反模式 — 用 ``inspect.getsource`` + ``hasattr``
    锁定"模块 import 了 helper",被 rename / 注释 / 死 import 误骗过。
    改用 ``mock.patch`` 真证"helper 被以正确参数调用",行为级合约。
    """
    from unittest.mock import patch

    from nexus.backend.permissions.write_tools import is_write_tool
    from nexus.backend.quality.middleware import QualityGateMiddleware

    ag_path = tmp_path / "AGENTS.md"
    ag_path.write_text("seed")
    mw = QualityGateMiddleware(filter=_StubFilter(), protected_paths=(str(ag_path),))

    tool_call = {"name": "edit_file", "args": {"file_path": str(ag_path)}}
    with patch("nexus.backend.quality.middleware.is_write_tool", wraps=is_write_tool) as m:
        mw._is_protected(tool_call)
        m.assert_called_once_with("edit_file")


def test_quality_middleware_invokes_helper_for_read_tool(tmp_path) -> None:
    """read_file 也会调 is_write_tool(被判定 False 后短路)。

    验证 helper 是无条件调用入口,不是只在写工具路径才进 — 防止有人
    在 QualityGate 里手写 ``if tool_name == "edit_file"`` 绕开 helper。
    """
    from unittest.mock import patch

    from nexus.backend.permissions.write_tools import is_write_tool
    from nexus.backend.quality.middleware import QualityGateMiddleware

    ag_path = tmp_path / "AGENTS.md"
    ag_path.write_text("seed")
    mw = QualityGateMiddleware(filter=_StubFilter(), protected_paths=(str(ag_path),))

    tool_call = {"name": "read_file", "args": {"file_path": str(ag_path)}}
    with patch("nexus.backend.quality.middleware.is_write_tool", wraps=is_write_tool) as m:
        mw._is_protected(tool_call)
        m.assert_called_once_with("read_file")


def test_hitl_middleware_invokes_helper_for_interrupt(tmp_path) -> None:
    """PathAwareHITL._should_interrupt 走 is_write_tool 判定写工具。"""
    from unittest.mock import patch

    from nexus.backend.middleware.hitl import PathAwareHITLMiddleware
    from nexus.backend.permissions.write_tools import is_write_tool

    mw = PathAwareHITLMiddleware(project_root=tmp_path)

    tool_call = {
        "name": "write_file",
        "args": {"file_path": str(tmp_path / "src" / "foo.py")},
    }
    with patch("nexus.backend.middleware.hitl.is_write_tool", wraps=is_write_tool) as m:
        mw._should_interrupt(tool_call)
        m.assert_called_once_with("write_file")


def test_fs_tool_order_baseline_0_7_6() -> None:
    """锁 deepagents FilesystemMiddleware._FS_TOOL_ORDER 在 0.7.6 的字面顺序。

    WHY: HITL / MemoryFilter / QualityGateMiddleware 拦截逻辑依赖字面工具名
    ('delete' / 'write_file' / ...)。若 0.7.7 / 0.8 改顺序或改名,
    is_write_tool() 仍能兜底(子串匹配),但 LLM 工具提示的展示顺序会变,
    触发 e2e flake。此断言作为 0.7.x 补丁升级窗口的基线锁;未来 0.7.7 / 0.8
    升级时按新字面值更新即可。
    """
    from deepagents.middleware.filesystem import _ALL_FS_TOOL_NAMES, _FS_TOOL_ORDER

    assert _FS_TOOL_ORDER == (
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
    )
    assert "delete" in _ALL_FS_TOOL_NAMES
    assert "execute" in _ALL_FS_TOOL_NAMES
