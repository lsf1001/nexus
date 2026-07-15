"""``nexus.backend.tools.run_skill`` 工具的单元测试。

覆盖三类路径:
  1. **正常**:skill_args 拼接 / cwd = skill 目录 / timeout=120 透传
  2. **边界**:skill_args 为空 → cmd 不带 trailing space;含空格 → shlex.quote
  3. **异常**:skill 不存在;缺 env var

WHY 重要:run_skill 是 LLM 触发 skill 的入口,内部转交 shell_run 走
沙箱 + 审计。这里只测 run_skill 自己的合约,不重测 shell_run 的沙箱。

WHY ``skill_args`` 不叫 ``args``:langchain 1.x Pydantic schema 把
``args`` / ``kwargs`` 当作 ``*args`` / ``**kwargs`` 合成字段剔除,同名
参数会丢,改名为 ``skill_args`` 一劳永逸。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend import tools as tools_mod
from nexus.backend.skills import SkillManifest
from nexus.backend.tools import run_skill

# === 异常路径:skill 不存在 / 缺 env ===


def test_run_skill_unknown_skill_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """未注册的 skill → 返回 error 字符串,含已加载列表。"""
    monkeypatch.setattr(tools_mod, "REGISTRY", {})  # 空 registry

    result = run_skill.invoke({"skill_name": "nonexistent", "skill_args": ""})

    assert "nonexistent" in result
    assert "未找到" in result or "not found" in result.lower()


def test_run_skill_missing_env_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """缺 requires env var → 返回明确错误,不调 shell_run。"""
    manifest = SkillManifest(
        name="needs_key",
        description="缺 key 的 skill",
        entrypoint="/tmp/needs_key/run.sh",
        requires=["MINIMAX_API_KEY"],
    )
    monkeypatch.setattr(tools_mod, "REGISTRY", {"needs_key": manifest})
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    calls: list[dict] = []

    def fake_shell_run(**kwargs):
        calls.append(kwargs)
        return "should not be called"

    monkeypatch.setattr(tools_mod, "shell_run", fake_shell_run)

    result = run_skill.invoke({"skill_name": "needs_key", "skill_args": "hello"})

    assert "MINIMAX_API_KEY" in result
    assert "环境变量" in result or "env" in result.lower()
    assert calls == []  # 关键:缺 env 时根本不该调 shell_run


# === 正常路径:monkeypatch shell_run 验证 cmd / cwd / timeout ===


def test_run_skill_dispatches_to_shell_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """正常路径:cmd = entrypoint + shlex.quote(skill_args),cwd = skill 目录,timeout=120。

    ``SKILLS_DIR`` 用 ``tmp_path`` 替代,避免污染真实 ``~/.nexus/skills/``。
    """
    skill_dir = tmp_path / "image_gen"
    skill_dir.mkdir()
    entrypoint = skill_dir / "run.sh"
    entrypoint.write_text("#!/bin/bash\necho hello\n", encoding="utf-8")

    # 隔离 SKILLS_DIR 到 tmp_path
    monkeypatch.setattr(tools_mod, "SKILLS_DIR", tmp_path)

    manifest = SkillManifest(
        name="image_gen",
        description="test",
        entrypoint=str(entrypoint),
        requires=[],
    )
    monkeypatch.setattr(tools_mod, "REGISTRY", {"image_gen": manifest})

    captured: dict = {}

    def fake_shell_run(command: str, cwd: str, timeout: int | None = None) -> str:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return "[exit_code=0] ok"

    monkeypatch.setattr(tools_mod, "shell_run", fake_shell_run)

    result = run_skill.invoke({"skill_name": "image_gen", "skill_args": "a koi fish"})

    assert "[exit_code=0] ok" in result
    assert captured["cwd"] == str(skill_dir)
    assert captured["timeout"] == 120
    assert "a koi fish" in captured["command"]
    assert str(entrypoint) in captured["command"]


def test_run_skill_empty_args_no_trailing_space(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """skill_args 为空 → cmd 末尾不残留空格。"""
    skill_dir = tmp_path / "foo"
    skill_dir.mkdir()
    entrypoint = skill_dir / "run.sh"
    entrypoint.write_text("#!/bin/bash\necho noop\n", encoding="utf-8")

    monkeypatch.setattr(tools_mod, "SKILLS_DIR", tmp_path)

    manifest = SkillManifest(
        name="foo",
        description="test",
        entrypoint=str(entrypoint),
    )
    monkeypatch.setattr(tools_mod, "REGISTRY", {"foo": manifest})

    captured: dict = {}

    def fake_shell_run(command: str, cwd: str, timeout: int | None = None) -> str:
        captured["command"] = command
        return "ok"

    monkeypatch.setattr(tools_mod, "shell_run", fake_shell_run)

    run_skill.invoke({"skill_name": "foo", "skill_args": ""})

    assert captured["command"] == str(entrypoint)  # 不带 trailing space


def test_run_skill_quotes_args_with_spaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """skill_args 含空格 → shlex.quote 转义,不会被 shell 拆成多参数。"""
    skill_dir = tmp_path / "bar"
    skill_dir.mkdir()
    entrypoint = skill_dir / "run.sh"
    entrypoint.write_text("#!/bin/bash\necho $1\n", encoding="utf-8")

    monkeypatch.setattr(tools_mod, "SKILLS_DIR", tmp_path)

    manifest = SkillManifest(
        name="bar",
        description="test",
        entrypoint=str(entrypoint),
    )
    monkeypatch.setattr(tools_mod, "REGISTRY", {"bar": manifest})

    captured: dict = {}

    def fake_shell_run(command: str, cwd: str, timeout: int | None = None) -> str:
        captured["command"] = command
        return "ok"

    monkeypatch.setattr(tools_mod, "shell_run", fake_shell_run)

    run_skill.invoke({"skill_name": "bar", "skill_args": "hello world; rm -rf /tmp/x"})

    # shlex.quote 会把空格 / ; 等包成 'hello world; rm -rf /tmp/x'
    cmd = captured["command"]
    # 关键:整段 skill_args 是被单引号包住的"一个参数",没被 shell split
    assert "'hello world; rm -rf /tmp/x'" in cmd
    assert str(entrypoint) in cmd
