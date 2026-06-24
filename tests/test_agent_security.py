"""agent 构造应启用 FilesystemPermission + interrupt_on。"""

from __future__ import annotations

from pathlib import Path

from nexus.backend.agent import build_interrupt_on_for_agent
from nexus.backend.permissions import build_default_permissions


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
