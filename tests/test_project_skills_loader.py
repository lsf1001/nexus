"""per-project skills 扫描 + symlink resolve 去重 — SPEC §4.4 / §5.3。

WHY 这个文件独立存在:
    已有 :mod:`nexus.backend.skills.loader` 测试在
    ``tests/test_skills_loader.py`` —— 那是测 lifespan 启动期调用的
    ``scan_skills_dir()``(供 system_prompt 拼装)。
    本文件测的是 :mod:`nexus.backend.projects.skills_loader.list_skills`,
    二者职责不同:
      - scan_skills_dir → 把 ~/.nexus/skills/ 解析成 SkillManifest,塞到 REGISTRY
      - list_skills     → 扫 project 的 skills/ 目录,返回轻量 dict 列表(供 REST)

覆盖三类路径:
  1. **正常**:default project 走软链到 ~/.nexus/skills/;
     custom project 走 ~/Nexus/projects/<name>/skills/
  2. **边界**:同 inode 不同路径(symlink resolve)→ 必须去重
  3. **异常**:不存在的 project_id / 无 skills/ 目录 → 空 list
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend.projects.skills_loader import list_skills


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """~/Nexus/projects/ — 实际路径由 ``NEXUS_HOME`` + ``storage._projects_root()``
    自动推导(``_get_nexus_home().parent / "Nexus" / "projects"``),无需手动注入。

    本 fixture 仅返回 :data:`tmp_path` 占位,使调用方阅读时知道
    "项目目录的根在 tmp_path 下"。
    """
    return tmp_path


def test_list_skills_for_default_uses_nexus_home_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 project 目录 + 软链 skills/ → ~/.nexus/skills/。

    验证 ``list_skills("default")`` 能从软链目标目录读到 skill。
    """
    # NEXUS_HOME 是 conftest.py 的 autouse fixture 已经设的 tmp_path/.nexus
    # 但本测试要自定义:让 nexus_home = tmp_path,
    # 这样 skills/ 软链和目标都在 tmp_path 内,可读性更高。
    nexus_home = tmp_path / "NexusHome"
    nexus_home.mkdir()
    (nexus_home / "skills").mkdir()
    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))

    projects_root = nexus_home.parent / "Nexus" / "projects"
    projects_root.mkdir(parents=True)

    default = projects_root / "default"
    default.mkdir()
    # skills/ 是软链 → ~/.nexus/skills/
    (default / "skills").symlink_to(nexus_home / "skills")

    # 真实 skill 在 ~/.nexus/skills/code-review/
    (nexus_home / "skills" / "code-review").mkdir()
    (nexus_home / "skills" / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: 审稿\nentrypoint: /tmp/code-review/run.sh\n---\nbody\n",
        encoding="utf-8",
    )

    # skills_loader 走 storage._projects_root()(用 NEXUS_HOME.parent + Nexus/projects)
    # 不需要额外 monkeypatch。
    skills = list_skills("default")
    names = {s["name"] for s in skills}
    assert "code-review" in names
    # 至少含 path/source 字段
    assert all("path" in s and "source" in s for s in skills)


def test_list_skills_dedupes_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §5.3:同一 inode 经软链访问 → 只返回 1 条。

    真实目录 ``~/.nexus/skills/shared-skill/`` 含 SKILL.md,
    ``~/Nexus/projects/default/skills`` 是软链 → 同一目录。
    期望 list_skills("default") 只返回 1 条 shared-skill。
    """
    nexus_home = tmp_path / "NexusHome"
    nexus_home.mkdir()
    (nexus_home / "skills").mkdir()

    # 真实 skill 目录
    real = nexus_home / "skills" / "shared-skill"
    real.mkdir()
    (real / "SKILL.md").write_text(
        "---\nname: shared-skill\ndescription: 共用 skill\nentrypoint: /tmp/shared/run.sh\n---\nbody\n",
        encoding="utf-8",
    )

    projects_root = nexus_home.parent / "Nexus" / "projects"
    projects_root.mkdir(parents=True)

    default = projects_root / "default"
    default.mkdir()
    # 软链:default/skills → nexus_home/skills
    (default / "skills").symlink_to(nexus_home / "skills")

    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))

    skills = list_skills("default")
    matching = [s for s in skills if s["name"] == "shared-skill"]
    assert len(matching) == 1, f"symlink resolve 后必须按 inode 去重,实际返回 {len(matching)} 条"


def test_list_skills_for_unknown_project_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不存在的 project_id → 空 list,不抛。"""
    nexus_home = tmp_path / "NexusHome"
    nexus_home.mkdir()
    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))

    # projects 目录为空 → 不存在的 project 必然无 skills
    projects_root = nexus_home.parent / "Nexus" / "projects"
    projects_root.mkdir(parents=True)

    skills = list_skills("nonexistent")
    assert skills == []


def test_list_skills_for_custom_project_uses_own_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非默认 project 走自己 ``~/Nexus/projects/<name>/skills/``。

    验证与 default project 的 skills 隔离 — my-blog 的 skill 不应泄漏到
    别的 project 的 list_skills 结果里。
    """
    nexus_home = tmp_path / "NexusHome"
    nexus_home.mkdir()
    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))

    projects_root = nexus_home.parent / "Nexus" / "projects"
    projects_root.mkdir(parents=True)

    custom = projects_root / "my-blog"
    custom.mkdir()
    (custom / "skills" / "seo-check").mkdir(parents=True)
    (custom / "skills" / "seo-check" / "SKILL.md").write_text(
        "---\nname: seo-check\ndescription: SEO\nentrypoint: /tmp/seo/run.sh\n---\nbody\n",
        encoding="utf-8",
    )

    skills = list_skills("my-blog")
    names = {s["name"] for s in skills}
    assert "seo-check" in names


def test_scan_dedups_same_inode_via_symlink(tmp_path: Path) -> None:
    """SPEC §5.3:同 inode 不同路径 → 只返回 1 条(防御性去重)。

    WHY 独立测 _scan:list_skills 的 default 短路直接跳到 ~/.nexus/skills,
    不经过软链 → dedup 分支不可达。这个测试直接喂 _scan 一个含软链的 root,
    让"两条路径→同 inode"真实场景跑通。
    """
    from nexus.backend.projects.skills_loader import _scan

    # 真实目录
    real_skill = tmp_path / "shared-skill"
    real_skill.mkdir()
    (real_skill / "SKILL.md").write_text("# Shared\n", encoding="utf-8")

    # 软链指向同一 inode(同一目录的不同路径)
    link = tmp_path / "shared-skill-link"
    link.symlink_to(real_skill)

    results = _scan(tmp_path)
    # 同 inode 的不同路径必须被去重
    assert len(results) == 1, f"expected 1, got {len(results)}: {results}"
    assert results[0]["name"] == "shared-skill"


def test_scan_does_not_dedup_distinct_skills(tmp_path: Path) -> None:
    """对照测试:不同 inode 必须保留为独立 skill。"""
    from nexus.backend.projects.skills_loader import _scan

    for name in ("alpha", "beta"):
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

    results = _scan(tmp_path)
    assert len(results) == 2
    names = sorted(r["name"] for r in results)
    assert names == ["alpha", "beta"]


def test_list_skills_filters_entries_without_skill_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """目录下有无 SKILL.md 的杂项文件 → 只列含 SKILL.md 的子目录。"""
    nexus_home = tmp_path / "NexusHome"
    nexus_home.mkdir()
    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))

    projects_root = nexus_home.parent / "Nexus" / "projects"
    projects_root.mkdir(parents=True)

    custom = projects_root / "p1"
    custom.mkdir()
    # 含 SKILL.md 的 → 应被列出
    (custom / "skills" / "real-skill").mkdir(parents=True)
    (custom / "skills" / "real-skill" / "SKILL.md").write_text(
        "---\nname: real-skill\ndescription: real\nentrypoint: /tmp/run.sh\n---\nbody\n",
        encoding="utf-8",
    )
    # 裸文件 / 缺 SKILL.md 的目录 → 不应被列出
    (custom / "skills" / "README.md").write_text("not a skill\n", encoding="utf-8")
    (custom / "skills" / "incomplete-skill").mkdir()

    skills = list_skills("p1")
    names = {s["name"] for s in skills}
    assert names == {"real-skill"}
