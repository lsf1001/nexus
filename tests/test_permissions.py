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


def test_build_default_permissions_only_allow_rules() -> None:
    """2026-06-30 重构:permissions 只含 allow rules(纯白名单)。

    历史版本含 ``mode="interrupt"`` 试图在 permissions 里表达 HITL/QualityGate
    拦截语义 — 但 deepagents 0.5.3 的 :class:`FilesystemPermission.mode` 只
    支持 ``Literal["allow", "deny"]``,``"interrupt"`` 是非法值被静默忽略。
    HITL 现由 :class:`PathAwareHITLMiddleware` 接管,QualityGate 由
    :class:`QualityGateMiddleware` 接管;permissions 只做基础白名单。
    """
    perms = build_default_permissions(Path("/tmp/proj"))
    modes = [p.mode for p in perms]
    assert all(m == "allow" for m in modes), f"permissions 应只含 allow rules,实际: {modes}"


def test_build_default_permissions_no_tmp_rule() -> None:
    """2026-06-30 重构:/tmp 不在 permissions 白名单。

    历史版本曾写 "``read /tmp/**`` allow" 让 /tmp 只读 — 但 LLM 实际想写
    /tmp 是要"临时缓存",产物路径(``~/.nexus/outputs/``)才是规范落点。
    现设计: /tmp 由 :class:`PathAwareHITLMiddleware` 的 ``_DANGEROUS_PREFIXES``
    直接 deny(``ToolMessage(status='error')``),不走 permissions。

    判定逻辑:permissions 里**不应有以 /tmp 开头的独立规则**。但允许
    ``/tmp`` 作为某项目 root 前缀的"白名单路径"出现(例:
    ``/private/tmp/proj/.nexus/**``,macOS 上 ``/tmp/proj`` resolve 后
    落在这里)。只看 path 的第一个 segment 是否命中 dangerous 根目录。
    """
    from pathlib import PurePosixPath

    perms = build_default_permissions(Path("/tmp/proj"))
    for p in perms:
        for path in p.paths:
            parts = PurePosixPath(path).parts
            # path 的根级 segment 不应是 dangerous 根(/tmp / etc / var ...)
            if parts:
                first = parts[0]
                assert first not in {"tmp", "etc", "usr", "bin", "sbin", "System", "Library"}, (
                    f"permissions 不应包含 dangerous 根路径 /{first}/... 的规则: {path}"
                )


def test_resolve_protected_paths_returns_absolute() -> None:
    """受保护路径解析为绝对路径。"""
    project_root = Path("/tmp/proj")
    paths = resolve_protected_paths(project_root)
    assert all(p.is_absolute() for p in paths)
    assert any("AGENTS.md" in str(p) for p in paths)


def test_is_write_to_protected_path_matches_agents_md() -> None:
    """工具调用命中用户级 ``~/.nexus/AGENTS.md`` 时返回 True。

    历史实现保护 ``{project_root}/.nexus/AGENTS.md`` 与
    ``{project_root}/nexus/.deepagents/AGENTS.md`` —— 2026-06 OpenClaw
    定位重设计后只保护用户级一条(``~/.nexus/AGENTS.md``),dev 时路径
    已无对应文件,删除。
    """
    protected = resolve_protected_paths(Path("/tmp/proj"))
    from nexus.backend.memory import USER_MEMORY_PATH

    assert (
        is_write_to_protected_path(
            tool_name="write_file",
            target_path=str(USER_MEMORY_PATH),
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
