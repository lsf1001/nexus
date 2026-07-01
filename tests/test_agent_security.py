"""agent 构造应启用 FilesystemPermission + PathAwareHITLMiddleware。

新架构(2026-06-30 重构):``permissions`` 只做基础白名单(纯 allow 规则),
HITL/QualityGate 由专门中间件在 wrap_tool_call 阶段拦截 —
:class:`nexus.backend.middleware.hitl.PathAwareHITLMiddleware` 与
:class:`nexus.backend.quality.middleware.QualityGateMiddleware`。

历史设计把 HITL 表达成 ``FilesystemPermission(mode="interrupt")`` 试图让
deepagents 自动派生 ``interrupt_on`` — 但 deepagents 0.5.3 的
``FilesystemPermission.mode`` 只支持 ``Literal["allow", "deny"]``,
``"interrupt"`` 是非法值被静默忽略,导致 5 个 E2E 场景全部 FAIL。本测试
守住新架构的不变量。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from nexus.backend.permissions import build_default_permissions, resolve_protected_paths


def test_agent_includes_filesystem_permissions() -> None:
    """create_agent 调用应包含 permissions 参数(白名单,只含 allow 规则)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    assert len(perms) >= 2
    # 全部 allow,没有 deny / interrupt(2026-06-30 重构后由 PathAwareHITLMiddleware 接管)
    assert all(p.mode == "allow" for p in perms), (
        f"permissions 应只含 allow 规则(HITL 由 PathAwareHITLMiddleware 接管): {[p.mode for p in perms]}"
    )


def test_interrupt_on_covers_write_tools() -> None:
    """``PathAwareHITLMiddleware`` 必须覆盖 write_file / edit_file 写工具集。

    2026-06-30 重构后,permissions 不再含 ``mode="interrupt"`` — HITL 拦截
    改为在 :class:`PathAwareHITLMiddleware.wrap_tool_call` 里对 write 工具
    做路径白名单判定。本测试守住"写工具拦截"这一不变量。
    """
    from nexus.backend.permissions.write_tools import is_write_tool as _is_write_tool

    # write_file / edit_file 必须命中
    for tool_name in ("write_file", "edit_file", "create_file", "apply_patch"):
        assert _is_write_tool(tool_name), f"{tool_name} 应被识别为写工具"
    # 只读工具不应被误判为写
    for tool_name in ("read_file", "ls", "glob", "grep", "internet_search"):
        assert not _is_write_tool(tool_name), f"{tool_name} 不应被误判为写工具"


def test_resolve_protected_paths_covers_all_agents_md() -> None:
    """resolve_protected_paths 必须覆盖 ``~/.nexus/AGENTS.md``。

    2026-06 重构后产品身份 hardcode 进代码,只有用户级一条 AGENTS.md 需要
    受 :class:`QualityGateMiddleware` 评估保护。
    """
    paths = resolve_protected_paths(Path("/tmp/proj"))
    assert len(paths) == 1, f"expected 1 protected path, got {len(paths)}: {paths}"
    assert all("AGENTS.md" in str(p) for p in paths), f"all paths should contain AGENTS.md: {paths}"
    str_paths = [str(p) for p in paths]
    assert any(".nexus/AGENTS.md" in p for p in str_paths), "应覆盖用户级 ~/.nexus/AGENTS.md"


def test_create_agent_passes_interrupt_permissions_to_deepagents() -> None:
    """``create_agent`` 必须把 ``permissions`` + ``PathAwareHITLMiddleware`` 同时挂上。

    2026-06-30 重构:HITL 不再走 deepagents 派生的 ``interrupt_on`` —
    由 :class:`PathAwareHITLMiddleware` 在 wrap_tool_call 阶段路径白名单
    触发 ``GraphInterrupt``。本测试守住两个不变量:
      1. ``create_agent`` 把 ``permissions`` 透传给 ``create_deep_agent``
         (作为 deepagents 自己的 _PermissionMiddleware 输入)
      2. ``create_agent`` 把 ``PathAwareHITLMiddleware`` 注入到 middleware 列表
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
            from nexus.backend.middleware.hitl import PathAwareHITLMiddleware

            with patch("deepagents.create_deep_agent") as mock_create:
                mock_create.return_value = MagicMock()
                create_agent(
                    model_name="m",
                    api_key="k",
                    api_base="https://x",
                )
                kwargs = mock_create.call_args.kwargs
                # 1. permissions 透传(纯白名单,无 interrupt 规则)
                assert "permissions" in kwargs, "permissions kwarg 缺失"
                permissions = kwargs["permissions"]
                assert all(p.mode == "allow" for p in permissions), (
                    f"permissions 应只含 allow 规则(HITL 已转交中间件): {[p.mode for p in permissions]}"
                )
                # 2. middleware 列表含 PathAwareHITLMiddleware
                middleware_list = kwargs.get("middleware") or []
                hitl_mws = [m for m in middleware_list if isinstance(m, PathAwareHITLMiddleware)]
                assert hitl_mws, (
                    "PathAwareHITLMiddleware 未挂到 create_deep_agent(middleware=) — HITL 完全失效(E2E 7/7 必 FAIL)"
                )
        finally:
            for k in ("NEXUS_HOME", "NEXUS_STORE", "NEXUS_CHECKPOINTER", "MINIMAX_API_KEY"):
                os.environ.pop(k, None)
