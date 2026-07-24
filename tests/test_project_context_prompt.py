"""<project_context> 段注入测试 — SPEC §4.6。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend.projects.storage import ensure_default_project


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    return tmp_path


def test_build_prompt_includes_project_name_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path
) -> None:
    """默认 Project 的 system prompt 段含 name / path / AGENTS.md 内容。"""
    from nexus.backend import db

    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    ensure_default_project()

    # 把 Project 路径重定向到 tmp_path 下,避免污染真实 ~/Nexus/projects/
    from nexus.backend.prompts import project_context

    monkeypatch.setattr(project_context, "_projects_root", lambda: tmp_path / "projects")
    # 写入一份 AGENTS.md
    default_dir = tmp_path / "projects" / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "AGENTS.md").write_text("# Custom agents\nline 1\nline 2\n")

    out = project_context.build_project_context_prompt("default")
    assert "name: default" in out
    assert "<project_context>" in out
    assert "AGENTS.md:" in out
    assert "# Custom agents" in out


def test_truncates_agents_md_to_200_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path) -> None:
    """AGENTS.md 内容超过 200 行时截断,避免 system prompt 过长。"""
    from nexus.backend import db

    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    ensure_default_project()

    from nexus.backend.prompts import project_context

    monkeypatch.setattr(project_context, "_projects_root", lambda: tmp_path / "projects")
    default_dir = tmp_path / "projects" / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "AGENTS.md").write_text("\n".join(f"line {i}" for i in range(500)))

    out = project_context.build_project_context_prompt("default")
    assert "line 199" in out
    assert "line 200" not in out  # 截断到 200 行
