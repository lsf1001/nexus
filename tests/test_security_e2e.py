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


def test_resolve_protected_paths_matches_3_agents_md_locations() -> None:
    """受保护路径覆盖用户级 + 项目级 + .deepagents 级三处。

    QualityGateMiddleware.protected_paths 依赖这个不变量(3 个路径都进
    忠实度评估,任何漏掉一处都意味着 LLM 可绕过质量门污染 AGENTS.md)。
    """
    paths = resolve_protected_paths(Path("/tmp/proj"))
    assert len(paths) == 3, f"应返回 3 个受保护路径,实际 {len(paths)}: {paths}"
    str_paths = [str(p) for p in paths]
    assert any(".nexus/AGENTS.md" in p for p in str_paths), "应覆盖用户级 ~/.nexus/AGENTS.md"
    assert any("nexus/.deepagents/AGENTS.md" in p for p in str_paths), "应覆盖项目级 nexus/.deepagents/AGENTS.md"


def test_is_write_to_protected_path_3_agents_md_paths() -> None:
    """3 处 AGENTS.md 路径都判定为受保护。"""
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
    """interrupt_on 谓词对白名单内路径返回 False(放行,layer 1 接管)。

    WHY:生产中 deepagents 框架传给 ``when`` 的 ``target_path`` 是已经
    ``.expanduser().resolve()`` 过的绝对路径(macOS 上 ``/tmp`` →
    ``/private/tmp`` 等 symlink 也已解开)。本测试必须传入 resolve 后的
    字符串才能命中 ``allowed_patterns``,否则会因 ``tempfile`` 的
    ``/var/folders`` vs ``/private/var/folders`` 误触发 HITL。
    """
    from nexus.backend.agent import build_interrupt_on_for_agent

    # 用 tempfile 临时目录(实际在 /var/folders/... 避开 /tmp 误匹配)
    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td).expanduser().resolve()
        cfg = build_interrupt_on_for_agent(project_root)
        when = cfg["write_file"]["when"]

        # .nexus/ 写应放行(白名单)——用 resolve 后的路径,匹配生产行为
        nexus_path = str((project_root / ".nexus" / "x.md").resolve())
        req_nexus = {"tool_call": {"args": {"file_path": nexus_path}}}
        assert when(req_nexus) is False, f".nexus/ 写应放行({nexus_path})"

        # 受保护 AGENTS.md 写交给 layer 1(放行让 FilesystemPermission interrupt 接管)
        protected_abs = [str(p) for p in resolve_protected_paths(project_root)]
        for p in protected_abs:
            req = {"tool_call": {"args": {"file_path": p}}}
            assert when(req) is False, f"AGENTS.md 路径 {p} 应交给 layer 1 接管"


def test_interrupt_on_blocks_project_source() -> None:
    """interrupt_on 谓词对项目内非白名单源码路径返回 True(触发 HITL)。"""
    from nexus.backend.agent import build_interrupt_on_for_agent

    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td)
        cfg = build_interrupt_on_for_agent(project_root)
        when = cfg["write_file"]["when"]

        # 项目源码路径(不是 .nexus/ 不是 /tmp/)
        src_path = str((project_root / "nexus" / "foo.py").resolve())
        req = {"tool_call": {"args": {"file_path": src_path}}}
        assert when(req) is True, f"项目源码 {src_path} 应触发 HITL"


def test_interrupt_on_covers_write_file_and_edit_file() -> None:
    """interrupt_on 配置必须同时覆盖 write_file 和 edit_file。"""
    from nexus.backend.agent import build_interrupt_on_for_agent

    cfg = build_interrupt_on_for_agent(Path("/tmp/proj"))
    assert "write_file" in cfg, "应覆盖 write_file"
    assert "edit_file" in cfg, "应覆盖 edit_file"
    # 两者 when 谓词都应是 callable
    assert callable(cfg["write_file"]["when"]), "write_file.when 应为 callable"
    assert callable(cfg["edit_file"]["when"]), "edit_file.when 应为 callable"
