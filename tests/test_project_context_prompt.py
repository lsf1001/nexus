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


def test_truncation_marker_shows_original_line_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path
) -> None:
    """截断标记应反映原文行数,而非切片后的 200。"""
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
    assert "原文共 500 行" in out
    assert "line 199" in out
    assert "line 200" not in out


def _init_db_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """初始化 DB 并确保默认 Project 存在(测试公共前置)。"""
    from nexus.backend import db

    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    ensure_default_project()


def test_skills_field_is_json_not_python_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path
) -> None:
    """skills / mcp_servers 字段应输出 JSON 数组,而非 Python list repr(单引号)。"""
    _init_db_and_default(monkeypatch)
    from nexus.backend.prompts import project_context

    monkeypatch.setattr(project_context, "_projects_root", lambda: tmp_path / "projects")
    monkeypatch.setattr(project_context, "list_skills", lambda pid: [{"name": "alpha"}, {"name": "beta"}])
    monkeypatch.setattr(project_context, "load_mcp_config_for_project", lambda pid: [{"name": "srv1"}])

    out = project_context.build_project_context_prompt("default")
    # JSON 数组:双引号,不含 Python repr 的单引号数组特征
    assert 'skills: ["alpha", "beta"]' in out
    assert 'mcp_servers: ["srv1"]' in out
    assert "skills: ['alpha'" not in out  # Python list repr 特征:单引号开头


def test_skills_empty_list_is_json_empty_array(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path
) -> None:
    """边界:无 skill 时输出 JSON 空数组 [],而非 Python 的 []('[' 后紧跟 ']')。"""
    _init_db_and_default(monkeypatch)
    from nexus.backend.prompts import project_context

    monkeypatch.setattr(project_context, "_projects_root", lambda: tmp_path / "projects")
    monkeypatch.setattr(project_context, "list_skills", lambda pid: [])
    monkeypatch.setattr(project_context, "load_mcp_config_for_project", lambda pid: [])

    out = project_context.build_project_context_prompt("default")
    assert "skills: []" in out
    assert "mcp_servers: []" in out


def test_skills_non_ascii_name_not_escaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path) -> None:
    """异常/边界:含中文的 skill 名不应被转成 \\uXXXX(ensure_ascii=False)。"""
    _init_db_and_default(monkeypatch)
    from nexus.backend.prompts import project_context

    monkeypatch.setattr(project_context, "_projects_root", lambda: tmp_path / "projects")
    monkeypatch.setattr(project_context, "list_skills", lambda pid: [{"name": "画图"}])
    monkeypatch.setattr(project_context, "load_mcp_config_for_project", lambda pid: [])

    out = project_context.build_project_context_prompt("default")
    assert 'skills: ["画图"]' in out
    assert "\\u" not in out
