"""agent 构造应启用 FilesystemPermission + interrupt_on。"""

from __future__ import annotations

from pathlib import Path

from nexus.backend.agent import build_interrupt_on_for_agent
from nexus.backend.permissions import build_default_permissions, resolve_protected_paths


def test_agent_includes_filesystem_permissions() -> None:
    """create_agent 调用应包含 permissions 参数(不为空 list)。"""
    perms = build_default_permissions(Path("/tmp/proj"))
    assert len(perms) >= 3
    assert any(p.mode == "interrupt" for p in perms)


def test_interrupt_on_covers_write_tools() -> None:
    """interrupt_on 配置必须覆盖 write_file 和 edit_file。"""
    cfg = build_interrupt_on_for_agent(Path("/tmp/proj"))
    assert "write_file" in cfg
    assert "edit_file" in cfg


def test_resolve_protected_paths_covers_all_agents_md() -> None:
    """resolve_protected_paths 必须覆盖 3 处 AGENTS.md(用户级 + 项目级 + .deepagents 级)。

    WHY: f86f2db 把 QualityGateMiddleware.protected_paths 从 2 个扩到 3 个,
    本测试守住"3 个路径都进了受保护集合"的不变量,防止未来又漏掉其中一处。
    """
    paths = resolve_protected_paths(Path("/tmp/proj"))
    assert len(paths) >= 3, f"expected ≥3 protected paths, got {len(paths)}: {paths}"
    assert all("AGENTS.md" in str(p) for p in paths), f"all paths should contain AGENTS.md: {paths}"
    str_paths = [str(p) for p in paths]
    assert any(".nexus/AGENTS.md" in p for p in str_paths), "应覆盖用户级 ~/.nexus/AGENTS.md"
    assert any("nexus/.deepagents/AGENTS.md" in p for p in str_paths), "应覆盖项目级 nexus/.deepagents/AGENTS.md"


def test_interrupt_on_when_dict_request_unpacks_correctly() -> None:
    """when 谓词必须能从 dict-shaped request 里正确解出 file_path(回归测试)。

    WHY: f86f2db 的 ``when_write_file`` 用了 ``hasattr(req, "tool_call")`` 判断,
    而测试/框架传的 req 是 ``dict``(有 ``tool_call`` key,不是 attribute),结果
    ``hasattr`` 恒为 False → ``tc = req`` → ``args = req.get("args", {})`` 拿空
    dict → ``file_path = ""`` → ``_should_interrupt("")`` 必返回 True(强制 HITL),
    屏蔽了下游所有逻辑(包括 symlink fix 后的白名单匹配)。

    本测试用 4 类场景守住解包后的判定语义。
    """
    cfg = build_interrupt_on_for_agent(Path("/tmp/proj"))
    when = cfg["write_file"]["when"]

    def _call(file_path: str) -> bool:
        return when({"tool_call": {"args": {"file_path": file_path}}})

    # 1. 写 .nexus/ 下任意文件 → 不应 interrupt(白名单放行)
    assert _call("/tmp/proj/.nexus/foo.md") is False, "白名单 .nexus/ 必须放行"
    # 2. 写 .nexus/AGENTS.md(protected) → 不 interrupt(由 layer 1 接管)
    pps = [str(p) for p in resolve_protected_paths(Path("/tmp/proj"))]
    assert _call(pps[1]) is False, "受保护 AGENTS.md 必须放行让 layer 1 接管"
    # 3. 写 /tmp/scratch.md → 不 interrupt(/tmp/ 白名单)
    assert _call("/tmp/scratch.md") is False, "/tmp/ 白名单必须放行"
    # 4. 写项目内源码(nexus/foo.py,resolve 后路径) → 必须 interrupt
    # 注:必须用 resolve 后的绝对路径,因为白名单还有 `^/tmp/`(设计:整个 /tmp/ 任意
    # 路径都允许写,如 /tmp/scratch.md;但 /private/tmp/.../nexus/foo.py 不会被此
    # pattern 误命中 → 走 interrupt 判定)。
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        project_root = Path(td)
        cfg = build_interrupt_on_for_agent(project_root)
        when = cfg["write_file"]["when"]
        resolved_src = str((project_root / "nexus" / "foo.py").resolve())
        # 白名单放过 .nexus/ 与 /tmp/(顶层),但 nexus/foo.py 在 /private/...
        # 不会被这两个 pattern 命中 → 必须 interrupt
        result = when({"tool_call": {"args": {"file_path": resolved_src}}})
        assert result is True, f"项目源码 {resolved_src} 必须触发 HITL,got {result}"
    # 5. 空 file_path → 保守 interrupt(强制 HITL)
    assert _call("") is True, "空 file_path 必须强制 HITL"
