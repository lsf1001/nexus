"""权限规则单元测试。"""

from __future__ import annotations

from pathlib import Path

from nexus.backend.permissions import (
    build_default_permissions,
    is_write_to_protected_path,
    resolve_protected_paths,
)


def test_build_default_permissions_has_no_deny() -> None:
    """默认规则应不含任何 deny(框架默认 allow,白名单显式放行)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    denies = [p for p in perms if p.mode == "deny"]
    assert denies == [], f"unexpected deny rules: {denies}"


def test_build_default_permissions_nexus_dir_writable() -> None:
    """.nexus/ 目录可读写。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    nexus_rule = next(p for p in perms if any(".nexus/**" in path for path in p.paths))
    assert "write" in nexus_rule.operations
    assert nexus_rule.mode == "allow"


def test_build_default_permissions_tmp_readonly() -> None:
    """/tmp/ 目录只读。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    tmp_rule = next(p for p in perms if "/tmp/**" in p.paths)
    assert tmp_rule.operations == ["read"]
    assert tmp_rule.mode == "allow"


def test_build_default_permissions_agents_md_interrupt() -> None:
    """AGENTS.md 写入必须 HITL。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    interrupt_rules = [p for p in perms if p.mode == "interrupt"]
    assert any("AGENTS.md" in path for r in interrupt_rules for path in r.paths)


def test_resolve_protected_paths_returns_absolute() -> None:
    """受保护路径解析为绝对路径。"""
    project_root = Path("/tmp/proj")
    paths = resolve_protected_paths(project_root)
    assert all(p.is_absolute() for p in paths)
    assert any("AGENTS.md" in str(p) for p in paths)


def test_is_write_to_protected_path_matches_agents_md() -> None:
    """工具调用命中 AGENTS.md 时返回 True。"""
    protected = resolve_protected_paths(Path("/tmp/proj"))
    assert (
        is_write_to_protected_path(
            tool_name="write_file",
            target_path="/tmp/proj/.nexus/AGENTS.md",
            protected_paths=protected,
        )
        is True
    )


def test_is_write_to_protected_path_rejects_normal_files() -> None:
    """普通文件返回 False。"""
    protected = resolve_protected_paths(Path("/tmp/proj"))
    assert (
        is_write_to_protected_path(
            tool_name="write_file",
            target_path="/tmp/proj/README.md",
            protected_paths=protected,
        )
        is False
    )
