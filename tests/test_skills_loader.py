"""``nexus.backend.skills`` loader 的单元测试。

覆盖三类路径:
  1. **正常**:完整 frontmatter + body;多文件;空目录
  2. **边界**:缺字段;坏 YAML;坏文件 skip
  3. **异常**:文件不存在;目录不存在

WHY 重要:`scan_skills_dir` 是 lifespan 启动期调用,单文件损坏就
连带不启动会阻断用户整个对话通道 → 必须 try-except 单文件 + log。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend.skills import (
    REGISTRY,
    SkillManifest,
    parse_skill_md,
    render_skills_for_prompt,
    scan_skills_dir,
)

# === parse_skill_md:正常路径 ===


def test_parse_skill_md_full_frontmatter(tmp_path: Path) -> None:
    """完整 frontmatter + body 分离正确。"""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: image_gen\n"
        "description: 用 image-01 生成图片\n"
        "triggers:\n"
        "  - 生成图片\n"
        "  - 画一张\n"
        "entrypoint: /Users/x/.nexus/skills/image_gen/run.sh\n"
        "inputs: 'prompt: 描述; aspect: 16:9'\n"
        "requires:\n"
        "  - MINIMAX_API_KEY\n"
        "---\n"
        "# image_gen\n"
        "\n"
        "调用 image-01 模型生成图片。\n",
        encoding="utf-8",
    )

    manifest = parse_skill_md(skill_md)

    assert isinstance(manifest, SkillManifest)
    assert manifest.name == "image_gen"
    assert manifest.description == "用 image-01 生成图片"
    assert manifest.triggers == ["生成图片", "画一张"]
    assert manifest.entrypoint == "/Users/x/.nexus/skills/image_gen/run.sh"
    assert manifest.inputs == "prompt: 描述; aspect: 16:9"
    assert manifest.requires == ["MINIMAX_API_KEY"]
    assert "调用 image-01 模型生成图片" in manifest.body


# === parse_skill_md:异常路径 ===


def test_parse_skill_md_missing_frontmatter_delimiter(tmp_path: Path) -> None:
    """缺 ``---`` 起始分隔符 → ValueError。"""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "name: foo\ndescription: bar\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="frontmatter"):
        parse_skill_md(skill_md)


def test_parse_skill_md_invalid_yaml(tmp_path: Path) -> None:
    """YAML 语法错(冒号 + 非法缩进)→ ValueError。"""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: image_gen\ndescription: : :\n  - bogus indent\n  ::::\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="(YAML|yaml|frontmatter)"):
        parse_skill_md(skill_md)


def test_parse_skill_md_missing_name_field(tmp_path: Path) -> None:
    """缺 ``name`` 字段 → Pydantic ValidationError。"""
    from pydantic import ValidationError

    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\ndescription: 缺 name\nentrypoint: /tmp/run.sh\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        parse_skill_md(skill_md)


def test_parse_skill_md_missing_entrypoint_field(tmp_path: Path) -> None:
    """缺 ``entrypoint`` 字段 → Pydantic ValidationError。"""
    from pydantic import ValidationError

    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: foo\ndescription: 缺 entrypoint\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        parse_skill_md(skill_md)


# === scan_skills_dir:正常路径 ===


def test_scan_skills_dir_empty(tmp_path: Path) -> None:
    """空目录 → REGISTRY 清空,返回 []。"""
    result = scan_skills_dir(tmp_path)
    assert result == []
    assert REGISTRY == {}


def test_scan_skills_dir_multiple_files(tmp_path: Path) -> None:
    """多文件 → 全加载到 REGISTRY,排序返回。"""
    for name in ("zeta", "alpha", "mu"):
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} skill\nentrypoint: /tmp/{name}/run.sh\n---\nbody\n",
            encoding="utf-8",
        )

    result = scan_skills_dir(tmp_path)

    assert sorted(m.name for m in result) == ["alpha", "mu", "zeta"]
    assert set(REGISTRY.keys()) == {"alpha", "mu", "zeta"}
    assert REGISTRY["alpha"].entrypoint == "/tmp/alpha/run.sh"


# === scan_skills_dir:异常路径(单文件 skip) ===


def test_scan_skills_dir_skips_corrupt_file(tmp_path: Path, caplog) -> None:
    """单个 SKILL.md 损坏 → 该文件 skip + 其他正常加载 + log warning。"""
    # 正常的
    good_dir = tmp_path / "good"
    good_dir.mkdir()
    (good_dir / "SKILL.md").write_text(
        "---\nname: good\ndescription: ok\nentrypoint: /tmp/good/run.sh\n---\nbody\n",
        encoding="utf-8",
    )
    # 损坏的(缺 --- 起始)
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text(
        "no frontmatter here\n",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        result = scan_skills_dir(tmp_path)

    assert len(result) == 1
    assert result[0].name == "good"
    assert "good" in REGISTRY
    assert "bad" not in REGISTRY
    assert any("bad" in rec.message for rec in caplog.records)


# === render_skills_for_prompt ===


def test_render_skills_for_prompt_empty() -> None:
    """空 manifest 列表 → 返回空字符串(让 _build_system_prompt 跳过这段)。"""
    assert render_skills_for_prompt([]) == ""


def test_render_skills_for_prompt_with_skills() -> None:
    """含 skill → markdown 段含 name/triggers/调用方式。"""
    manifests = [
        SkillManifest(
            name="image_gen",
            description="用 image-01 生成图片",
            triggers=["生成图片", "画一张"],
            entrypoint="/tmp/run.sh",
        ),
    ]
    text = render_skills_for_prompt(manifests)
    assert "image_gen" in text
    assert "生成图片" in text
    assert "run_skill" in text  # 告诉 LLM 怎么调
