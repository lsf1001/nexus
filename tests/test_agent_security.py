"""agent 构造应启用 FilesystemPermission + interrupt_on。

新架构(2026-06-24 之后):``interrupt_on`` 不再手动构造,而是让 deepagents
从 ``permissions`` mode="interrupt" 规则自动派生。测试现在验证
``create_agent`` 透传的 ``permissions`` 是否包含正确的 allow + interrupt
规则 — 这是触发 HITL 的真正入口。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from nexus.backend.permissions import build_default_permissions, resolve_protected_paths


def test_agent_includes_filesystem_permissions() -> None:
    """create_agent 调用应包含 permissions 参数(不为空 list)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    assert len(perms) >= 3
    assert any(p.mode == "interrupt" for p in perms)


def test_interrupt_on_covers_write_tools() -> None:
    """``permissions`` 必须含 mode="interrupt" 规则,且覆盖 write_file 工具集。

    WHY:deepagents 从 mode="interrupt" 规则自动派生 ``interrupt_on``。
    规则必须在 ``operations`` 列表里包含 ``"write"``(覆盖 write_file / edit_file
    两个写工具)才会在 deepagents 中触发 HITL。
    """
    perms = build_default_permissions(Path("/tmp/proj"))
    interrupt_perms = [p for p in perms if p.mode == "interrupt"]
    assert interrupt_perms, "至少 1 条 interrupt 规则"
    # 每条 interrupt 规则都必须含 write 操作(deepagents 把 write 映射到
    # write_file / edit_file 两个工具的 interrupt_on)
    for rule in interrupt_perms:
        assert "write" in rule.operations, f"interrupt 规则必须覆盖 write 操作: {rule}"


def test_resolve_protected_paths_covers_all_agents_md() -> None:
    """resolve_protected_paths 必须覆盖 3 处 AGENTS.md(用户级 + 项目级 + .deepagents 级)。

    WHY: f86f2db 把 QualityGateMiddleware.protected_paths 从 2 个扩到 3 个,
    本测试守住"3 个路径都进了受保护集合"的不变量,防止未来又漏掉其中一处。
    """
    paths = resolve_protected_paths(Path("/tmp/proj"))
    assert len(paths) == 1, f"expected 1 protected path, got {len(paths)}: {paths}"
    assert all("AGENTS.md" in str(p) for p in paths), f"all paths should contain AGENTS.md: {paths}"
    str_paths = [str(p) for p in paths]
    assert any(".nexus/AGENTS.md" in p for p in str_paths), "应覆盖用户级 ~/.nexus/AGENTS.md"


def test_create_agent_passes_interrupt_permissions_to_deepagents() -> None:
    """``create_agent`` 必须把 ``permissions`` 透传给 ``create_deep_agent``。

    新架构下,deepagents 看到 ``mode="interrupt"`` 规则就自动给
    write_file / edit_file 装上 interrupt_on 谓词。Nexus 这一侧
    不需要再手写 when 函数,只要保证透传即可。
    """
    # 契约测试:避免真起 AsyncSqliteStore/AsyncSqliteSaver(同库持锁)
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td)
        os.environ["NEXUS_HOME"] = str(project_root / ".nexus")
        os.environ["NEXUS_STORE"] = "memory"
        os.environ["NEXUS_CHECKPOINTER"] = "memory"
        os.environ["MINIMAX_API_KEY"] = "test-key"
        try:
            from nexus.backend.agent import create_agent

            with patch("deepagents.create_deep_agent") as mock_create:
                mock_create.return_value = MagicMock()
                create_agent(
                    model_name="m",
                    api_key="k",
                    api_base="https://x",
                )
                kwargs = mock_create.call_args.kwargs
                assert "permissions" in kwargs, "permissions kwarg 缺失 — deepagents 不会派生 interrupt_on"
                permissions = kwargs["permissions"]
                interrupt_rules = [p for p in permissions if p.mode == "interrupt"]
                assert interrupt_rules, "至少需要 1 条 mode='interrupt' 规则触发 HITL"
                # 每条 interrupt 规则必须含 write(覆盖 write_file / edit_file)
                for rule in interrupt_rules:
                    assert "write" in rule.operations, (
                        f"interrupt 规则必须覆盖 write 操作(派生 write_file/edit_file 的 interrupt_on): {rule}"
                    )
        finally:
            for k in ("NEXUS_HOME", "NEXUS_STORE", "NEXUS_CHECKPOINTER", "MINIMAX_API_KEY"):
                os.environ.pop(k, None)
