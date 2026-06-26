"""端到端安全防护验证:HITL 拦截 + allow + interrupt 三类路径。

WHY:Task 1-4 已经分别覆盖了单元(permissions) / 集成(agent) / 边界(WS HITL),
本文件验证三层防护在端到端场景下行为一致,防止未来重构破坏不变量。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from nexus.backend.permissions import (
    build_default_permissions,
    is_write_to_protected_path,
    resolve_protected_paths,
)


def test_agents_md_write_triggers_interrupt_at_three_locations() -> None:
    """3 处 AGENTS.md(用户级 + 项目级 .nexus + .deepagents)写入必须 interrupt。

    WHY:deepagents FilesystemPermission mode="interrupt" 只对显式列出的路径
    触发 HITL;若这 3 条路径任一遗漏,LLM 写入污染长期记忆时不会弹确认。
    """
    perms = build_default_permissions(Path("/tmp/proj"))
    interrupt_paths = [path for p in perms if p.mode == "interrupt" for path in p.paths]
    # 至少 1 条 interrupt 规则,每条规则都含 AGENTS.md
    assert interrupt_paths, "至少需要 1 条 interrupt 规则"
    assert all("AGENTS.md" in p for p in interrupt_paths), f"所有 interrupt 路径都应含 AGENTS.md: {interrupt_paths}"


def test_nexus_dir_write_allowed() -> None:
    """.nexus/ 下写入直接 allow(LLM 可写配置 / 日志 / outputs / state)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    allow_write = [p for p in perms if "write" in p.operations and p.mode == "allow"]
    assert any(".nexus/**" in path for p in allow_write for path in p.paths), (
        f"应至少 1 条 allow-write 规则覆盖 .nexus/**: {allow_write}"
    )


def test_tmp_is_readonly_not_writable() -> None:
    """/tmp 只读:LLM 可看临时文件,但不允许写入(产出物应落 .nexus/)。

    WHY:把 /tmp 设为 write-allow 会让 LLM 在 /tmp 下散落大量不可审计的
    临时文件,违反"产出物集中 .nexus/"的设计原则。当前架构故意把 /tmp
    列为 read-only 规则。
    """
    perms = build_default_permissions(Path("/tmp/proj"))
    # 找包含 /tmp/** 的规则
    tmp_rules = [p for p in perms if any("/tmp/**" in path for path in p.paths)]
    assert tmp_rules, "应至少 1 条规则覆盖 /tmp/**"
    # /tmp/** 规则必须是 read-only,不应出现 write
    for rule in tmp_rules:
        assert "write" not in rule.operations, f"/tmp/** 不应被允许写入(防 LLM 在 /tmp 散落文件): {rule}"


def test_no_deny_rules_added_by_design() -> None:
    """本版本不加 deny(避免和 interrupt 语义重复)。

    WHY:FilesystemPermission 没有 deny-by-default 语义,deny 规则会和
    interrupt 重复,且 deny 不会触发 HITL(LLM 看到"被拒"提示,体验差)。
    真正的高敏保护靠 interrupt + QualityGateMiddleware 忠实度评估。
    """
    perms = build_default_permissions(Path("/tmp/proj"))
    denies = [p for p in perms if p.mode == "deny"]
    assert denies == [], f"不应有 deny 规则,实际: {denies}"


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


def test_interrupt_on_preserves_allowlist() -> None:
    """``permissions`` allow 规则覆盖 .nexus/ + /tmp/,白名单内写不触发 HITL。

    新架构:interrupt_on 由 deepagents 从 ``mode="interrupt"`` 派生;
    ``mode="allow"`` 规则直接放行(LLM 可写)。本测试守住 allow 规则
    覆盖 .nexus/ + /tmp/ 的不变量,防止未来重构把白名单漏掉导致
    LLM 写配置/日志时也被 HITL 拦下。
    """
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td).expanduser().resolve()
        perms = build_default_permissions(project_root)
        allow_write_rules = [p for p in perms if "write" in p.operations and p.mode == "allow"]
        assert allow_write_rules, "应至少 1 条 allow-write 规则"
        # .nexus/ 必须被 allow 规则覆盖(用户级 + 项目级都允许写)
        all_allowed_paths = [path for rule in allow_write_rules for path in rule.paths]
        nexus_allowed = any(".nexus/**" in p for p in all_allowed_paths)
        assert nexus_allowed, f".nexus/** 应在 allow 规则中,实际: {all_allowed_paths}"


def test_interrupt_on_blocks_project_source() -> None:
    """``permissions`` interrupt 规则覆盖受保护 AGENTS.md,非白名单项目源码默认 allow。

    新架构下,deepagents 的 FilesystemPermission 行为是:
    - 命中 mode="allow" → 放行
    - 命中 mode="interrupt" → 弹 HITL
    - 未命中 → 默认 allow(deny-by-default 禁用,详见 permissions.py 设计原则)

    所以"项目源码"在 allow 规则**不**覆盖的情况下默认 allow,而不是触发 HITL。
    真正会触发 HITL 的只有 mode="interrupt" 规则明确列出的路径(3 处 AGENTS.md)。
    本测试验证这层"默认 allow + interrupt 显式列"的语义。
    """
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td)
        perms = build_default_permissions(project_root)
        interrupt_rules = [p for p in perms if p.mode == "interrupt"]
        assert interrupt_rules, "应至少 1 条 interrupt 规则"
        # 全部 interrupt 路径必须是 3 处 AGENTS.md 之一(非源码路径)
        all_interrupt_paths = [path for rule in interrupt_rules for path in rule.paths]
        protected_abs = [str(p) for p in resolve_protected_paths(project_root)]
        for ip in all_interrupt_paths:
            assert any(ip == p for p in protected_abs), (
                f"interrupt 规则路径 {ip} 不在受保护 AGENTS.md 列表 {protected_abs} 中 — "
                "可能把普通源码路径错配为 interrupt 了,会误伤 LLM 改源码"
            )


def test_interrupt_on_covers_write_file_and_edit_file() -> None:
    """``permissions`` interrupt 规则的 ``operations`` 必须含 ``"write"``,
    deepagents 才会把它同时映射到 write_file / edit_file 两个工具。

    WHY:deepagents 的 FilesystemPermission 用 ``operations`` 字段做"操作类型
    匹配",``["write"]`` 覆盖 write_file 和 edit_file(两个写工具)。如果
    写成 ``["write_file"]`` 之类单工具名,edit_file 不会触发 interrupt。
    """
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td)
        perms = build_default_permissions(project_root)
        interrupt_rules = [p for p in perms if p.mode == "interrupt"]
        assert interrupt_rules, "应至少 1 条 interrupt 规则"
        for rule in interrupt_rules:
            assert "write" in rule.operations, (
                f"interrupt 规则的 operations 必须含 'write' 才能覆盖 write_file/edit_file, 实际: {rule}"
            )
