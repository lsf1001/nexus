"""per-project mcp.json 加载 — SPEC §4.5 / §5.2。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.backend.projects.mcp_loader import (
    find_project_mcp_config,
    load_mcp_config_for_project,
)


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    return root


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    return tmp_path


def test_default_project_uses_legacy_paths(
    projects_root: Path, nexus_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认 project 的 mcp.json 路径降级 ~/.nexus/mcp/config.json → ~/.mcp.json。"""
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)

    legacy = nexus_home / "mcp" / "config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"mcpServers": {"x": {"command": "echo"}}}))

    cfg = load_mcp_config_for_project("default")
    assert any(s.get("name") == "x" for s in cfg)


def test_custom_project_uses_own_mcp_json(projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)

    custom = projects_root / "my-blog"
    custom.mkdir()
    (custom / "mcp.json").write_text(json.dumps({"mcpServers": {"blog-cms": {"command": "node", "args": ["cms"]}}}))
    cfg = load_mcp_config_for_project("my-blog")
    assert any(s.get("name") == "blog-cms" for s in cfg)


def test_unknown_project_returns_empty(projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)
    assert load_mcp_config_for_project("nonexistent") == []


def test_returns_raw_server_list(projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """返回原始 server list,交给现有 load_all_mcp_tools 走原路径。"""
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)
    custom = projects_root / "p1"
    custom.mkdir()
    (custom / "mcp.json").write_text(json.dumps({"mcpServers": {"a": {"command": "a"}, "b": {"command": "b"}}}))
    cfg = load_mcp_config_for_project("p1")
    names = {s.get("name") for s in cfg}
    assert names == {"a", "b"}


def test_find_project_mcp_config_returns_existing_paths_only(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """find_project_mcp_config 只返回真实存在的候选路径(边界:目录空时空 list)。"""
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)
    assert find_project_mcp_config("ghost") == []
