"""端到端安全防护验证:三层防护(permissions 白名单 + PathAwareHITLMiddleware HITL
+ QualityGateMiddleware 评估)在端到端场景下行为一致。

WHY:2026-06-30 重构后,HITL 不再由 ``FilesystemPermission(mode="interrupt")``
派生(该字段在 deepagents 0.5.3 是非法值,被静默忽略),改为由
:class:`nexus.backend.middleware.hitl.PathAwareHITLMiddleware` 在
``wrap_tool_call`` 阶段做路径白名单 + 危险路径判定。本测试守住新架构的
不变量,防止未来重构再次破坏 HITL 拦截语义。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from nexus.backend.middleware.hitl import PathAwareHITLMiddleware
from nexus.backend.permissions import (
    build_default_permissions,
    is_write_to_protected_path,
    resolve_protected_paths,
)
from nexus.backend.permissions.write_tools import is_write_tool


def test_agents_md_triggers_quality_gate_not_hitl() -> None:
    """2026-06-30 重构:AGENTS.md 写入由 QualityGateMiddleware 评估,
    不是 PathAwareHITLMiddleware 弹 HITL(避免双重弹窗)。

    行为契约:
      - PathAwareHITLMiddleware._is_protected() 对 ``~/.nexus/AGENTS.md``
        返回 True(在 protected 集合中)→ _should_interrupt() 返回 False
        → 中间件透传,不弹 HITL。
      - 真正的"机器判断"由 :class:`QualityGateMiddleware` 跑 faithfulness 评估。
    """
    project_root = Path("/tmp/proj")
    protected_abs = tuple(str(p) for p in resolve_protected_paths(project_root))
    mw = PathAwareHITLMiddleware(project_root=project_root, protected_paths=protected_abs)
    # 写 AGENTS.md: 应跳过 HITL(让 QualityGate 评估)
    assert protected_abs, "应至少有 1 个受保护路径"
    tool_call = {
        "name": "write_file",
        "id": "tc1",
        "args": {"file_path": str(protected_abs[0]), "content": "x"},
    }
    assert not mw._should_interrupt(tool_call), (
        "AGENTS.md 写入应跳过 HITL(QualityGate 兜底),不应再弹确认 — 避免双重弹窗"
    )


def test_nexus_dir_write_allowed() -> None:
    """.nexus/ 下写入直接 allow(LLM 可写配置 / 日志 / outputs / state)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    allow_write = [p for p in perms if "write" in p.operations and p.mode == "allow"]
    assert any(".nexus/**" in path for p in allow_write for path in p.paths), (
        f"应至少 1 条 allow-write 规则覆盖 .nexus/**: {allow_write}"
    )


def test_tmp_is_dangerous_not_writable() -> None:
    """/tmp 是 PathAwareHITLMiddleware 的 dangerous 路径,直接 deny 不弹 HITL。

    2026-06-30 重构:历史版本把 /tmp 列为 "read-only allow"(LLM 可看但不可写),
    但深 agents 0.5.3 _PermissionMiddleware 对 "read-only allow" 不阻断 write
    调用(因为 deepagents 框架允许"未命中 allow-write 规则 → 默认 allow")。
    实测 LLM 仍可写 /tmp。当前设计:
      - permissions 不含 /tmp 规则(只看 dangerous 根前缀,不查字符串含 /tmp)
      - PathAwareHITLMiddleware._should_deny() 对 /tmp/** 直接返回 deny,
        生成 ``ToolMessage(status='error')`` 阻断,LLM 反思不再写
    """
    from pathlib import PurePosixPath

    perms = build_default_permissions(Path("/tmp/proj"))
    # permissions 不应包含以 /tmp 为根的规则(但允许 /tmp 作为项目 root 前缀,
    # 例如 ``/private/tmp/proj/.nexus/**`` —— 这里第一段是 ``private``,合法)
    for p in perms:
        for path in p.paths:
            parts = PurePosixPath(path).parts
            if parts and parts[0] == "tmp":
                raise AssertionError(f"permissions 不应包含以 /tmp 为根的规则: {p}")

    # PathAwareHITLMiddleware 应把 /tmp 视为 dangerous
    with tempfile.TemporaryDirectory() as td:
        mw = PathAwareHITLMiddleware(project_root=Path(td))
        tool_call = {
            "name": "write_file",
            "id": "tc1",
            "args": {"file_path": "/tmp/e2e_scratch.md", "content": "x"},
        }
        assert mw._should_deny(tool_call), "/tmp 写应被 _should_deny 拦截,直接 deny 不弹 HITL"
        assert not mw._should_interrupt(tool_call), "/tmp 写不应触发 HITL(走 deny 路径)"


def test_no_deny_rules_in_permissions_by_design() -> None:
    """2026-06-30 重构:permissions 不加 deny — deny 由 PathAwareHITLMiddleware._should_deny 接管。

    WHY:FilesystemPermission 的 deny 规则只对 _PermissionMiddleware 生效,
    但 HITL 必须由中间件触发 GraphInterrupt 才能让 WS 端发 confirmation_request。
    把 deny 和 HITL 拆到两层更清晰:permissions 是 _PermissionMiddleware
    的输入(纯白名单),PathAwareHITLMiddleware 负责 GraphInterrupt 链路。
    """
    perms = build_default_permissions(Path("/tmp/proj"))
    denies = [p for p in perms if p.mode == "deny"]
    assert denies == [], f"permissions 不应有 deny 规则(改由 PathAwareHITLMiddleware 接管): {denies}"


def test_resolve_protected_paths_matches_user_agents_md_only() -> None:
    """受保护路径只剩用户级 ``~/.nexus/AGENTS.md``(OpenClaw 定位)。

    QualityGateMiddleware.protected_paths 依赖这个不变量(只保护用户级
    一条;任何漏判意味着 LLM 可绕过质量门污染用户长期偏好)。
    """
    paths = resolve_protected_paths(Path("/tmp/proj"))
    assert len(paths) == 1, f"应返回 1 个受保护路径,实际 {len(paths)}: {paths}"
    str_paths = [str(p) for p in paths]
    assert any(".nexus/AGENTS.md" in p for p in str_paths), "应覆盖用户级 ~/.nexus/AGENTS.md"


def test_is_write_to_protected_path_user_agents_md() -> None:
    """用户级 ``~/.nexus/AGENTS.md`` 路径判定为受保护。"""
    protected = resolve_protected_paths(Path("/tmp/proj"))
    for sample_path in protected:
        assert (
            is_write_to_protected_path(
                tool_name="write_file",
                target_path=str(sample_path),
                protected_paths=protected,
            )
            is True
        ), f"{sample_path} 应被判定为受保护"
    # 普通文件仍然 False
    assert (
        is_write_to_protected_path(
            tool_name="write_file",
            target_path="/tmp/proj/README.md",
            protected_paths=protected,
        )
        is False
    )


def test_path_aware_hitl_preserves_allowlist() -> None:
    """PathAwareHITLMiddleware 的白名单内写不触发 HITL,直接放行。

    新架构:permissions + PathAwareHITLMiddleware 双层都做白名单,
    permissions 喂 deepagents 自己的 _PermissionMiddleware(纯 allow),
    PathAwareHITLMiddleware 路径白名单在中间件层 early-return。
    """
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td).expanduser().resolve()
        mw = PathAwareHITLMiddleware(project_root=project_root)
        # 项目级 .nexus/outputs/ → 白名单内,放行
        tool_call = {
            "name": "write_file",
            "id": "tc1",
            "args": {
                "file_path": str(project_root / ".nexus" / "outputs" / "test.md"),
                "content": "x",
            },
        }
        assert not mw._should_interrupt(tool_call), "项目级 .nexus/outputs/ 写应放行,不触发 HITL"
        assert not mw._should_deny(tool_call), "白名单内不应被 deny"
        # 用户级 ~/.nexus/outputs/ → 白名单内,放行
        tool_call_user = {
            "name": "write_file",
            "id": "tc2",
            "args": {
                "file_path": str(Path.home() / ".nexus" / "outputs" / "test.md"),
                "content": "x",
            },
        }
        assert not mw._should_interrupt(tool_call_user), "用户级 .nexus/outputs/ 写应放行"


def test_path_aware_hitl_blocks_project_source() -> None:
    """PathAwareHITLMiddleware 对非白名单 + 非 dangerous + 非 protected 路径触发 HITL。

    新架构下,deepagents FilesystemPermission 已不表达 HITL 语义,
    所有 HITL 拦截都在 PathAwareHITLMiddleware.wrap_tool_call 完成。
    项目源码路径(``nexus/backend/foo.py``)是典型的"非白名单" → 触发 HITL。
    """
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td)
        mw = PathAwareHITLMiddleware(project_root=project_root)
        tool_call = {
            "name": "write_file",
            "id": "tc1",
            "args": {
                "file_path": str(project_root / "nexus" / "backend" / "e2e_src.py"),
                "content": "print('e2e')",
            },
        }
        assert mw._should_interrupt(tool_call), "项目源码路径应触发 PathAwareHITLMiddleware HITL(E2E 7/7 必 PASS)"
        assert not mw._should_deny(tool_call), "项目源码不应被 deny(允许用户弹窗决策)"


def test_path_aware_hitl_covers_write_file_and_edit_file() -> None:
    """PathAwareHITLMiddleware 拦截必须覆盖 write_file / edit_file 等写工具。"""
    # is_write_tool 已覆盖 write_file / edit_file / create_file 等
    for tool_name in ("write_file", "edit_file", "create_file", "apply_patch", "patch_file"):
        assert is_write_tool(tool_name), f"{tool_name} 应被识别为写工具"

    # 只读工具不应被误判
    for tool_name in ("read_file", "ls", "glob", "grep"):
        assert not is_write_tool(tool_name), f"{tool_name} 不应被误判为写工具"

    # PathAwareHITLMiddleware 实例:edit_file 命中 HITL 拦截
    with tempfile.TemporaryDirectory() as td:
        mw = PathAwareHITLMiddleware(project_root=Path(td))
        for tool_name in ("write_file", "edit_file"):
            tc = {
                "name": tool_name,
                "id": "tc1",
                "args": {
                    "file_path": str(Path(td) / "nexus" / "backend" / "x.py"),
                    "content": "x",
                    "old_string": "",
                    "new_string": "x",
                },
            }
            assert mw._should_interrupt(tc), f"{tool_name} 应触发 HITL"
