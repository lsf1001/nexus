"""``nexus.backend.skills.loader``:扫描 + 解析 + 渲染 SKILL.md。

为什么是 module-level REGISTRY 而不是 class:
- lifespan 在 main.py 里直接 ``scan_skills_dir()`` 一次即可,不需要
  显式注入;run_skill 工具和 _build_system_prompt 都从这个 module
  导入同一份 REGISTRY,进程内一份足够。
- 调试时 reload 只需 ``scan_skills_dir()`` 再调一次即可。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import SkillManifest

logger = logging.getLogger(__name__)


SKILLS_DIR = Path.home() / ".nexus" / "skills"

# 进程内一份;lifespan 启动时调 scan_skills_dir() 填充,后续直接读
REGISTRY: dict[str, SkillManifest] = {}


_FRONTMATTER_DELIM = "---"


def parse_skill_md(path: Path) -> SkillManifest:
    """解析单个 SKILL.md → SkillManifest。

    失败时抛 ValueError(frontmatter 缺失 / YAML 语法错)或 Pydantic
    ValidationError(字段缺失)——callers 在 :func:`scan_skills_dir`
    里 try-except 吞掉,不让单文件坏掉连累整个启动。

    Args:
        path: ``<skill_dir>/SKILL.md`` 绝对路径。

    Returns:
        校验通过的 SkillManifest。

    Raises:
        ValueError: 缺 ``---`` 分隔符 / YAML 语法错。
        ValidationError: 缺必填字段(name / entrypoint 等)。
    """
    raw = path.read_text(encoding="utf-8")

    # 简易 frontmatter 分隔:开头必须是 ``---\n``
    if not raw.startswith(_FRONTMATTER_DELIM + "\n"):
        raise ValueError(f"SKILL.md frontmatter 缺失(需要以 '{_FRONTMATTER_DELIM}\\n' 开头): {path}")

    # 第一个 ``\n---\n`` 之后是 body
    try:
        _, rest = raw.split("\n", 1)
        fm_block, body = rest.split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError(f"SKILL.md 缺结束分隔符 '{_FRONTMATTER_DELIM}': {path}") from exc

    try:
        data = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"SKILL.md YAML 解析失败: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"SKILL.md frontmatter 必须是 mapping: {path}")

    data["body"] = body.strip()
    # Pydantic 校验缺字段 → ValidationError
    return SkillManifest.model_validate(data)


def scan_skills_dir(skills_dir: Path = SKILLS_DIR) -> list[SkillManifest]:
    """扫描目录下的所有 SKILL.md → 填充 REGISTRY + 返回 manifests 列表。

    行为契约:
      - 目录不存在 → 清空 REGISTRY,返回 [],**不**报错(用户第一次
        启动还没建过 ~/.nexus/skills 是合法状态)
      - 单文件损坏 → 该文件 skip + log warning,**不**阻断其他文件加载
      - 排序按 skill 目录名(确定性输出,便于 prompt diff)

    Args:
        skills_dir: 扫描根目录,默认 ``~/.nexus/skills``。

    Returns:
        成功解析的 SkillManifest 列表(已按 name 排序)。
    """
    REGISTRY.clear()

    if not skills_dir.exists():
        logger.info("[skills] 目录不存在,跳过扫描: %s", skills_dir)
        return []

    manifests: list[SkillManifest] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            manifest = parse_skill_md(skill_md)
        except (ValueError, ValidationError) as exc:
            # 单文件坏不阻断整个启动,只 warn
            logger.warning(
                "[skills] 跳过损坏的 SKILL.md: %s, reason=%s",
                skill_md,
                exc,
            )
            continue
        REGISTRY[manifest.name] = manifest
        manifests.append(manifest)

    logger.info("[skills] loaded %d skill(s): %s", len(manifests), sorted(m.name for m in manifests))
    return manifests


def render_skills_for_prompt(manifests: list[SkillManifest]) -> str:
    """把 manifest 列表渲染成 system prompt 末尾的 markdown 段。

    空列表 → 返回 ``""``(让 :func:`_build_system_prompt` 跳过这段)。

    WHY 单调格式:LLM 在 user prompt 命中 trigger 时,需要快速对照
    "哪个 skill 名字 + 怎么调用 + 接什么参数" → 单调列表比散文好扫读。
    """
    if not manifests:
        return ""

    lines = [
        "## 已加载 Skills(用户运行时目录 ~/.nexus/skills/)",
        "",
        "用户在你的运行环境里放了以下 skills。当你判断用户意图命中某个 trigger 时,",
        '**必须**用 ``run_skill(skill_name="<name>", args="<描述>")`` 工具触发。',
        "**禁止**自己编造脚本路径或绕过 run_skill 直接调 shell_run。",
        "",
    ]
    for m in manifests:
        triggers = ", ".join(f"``{t}``" for t in m.triggers) if m.triggers else "(无 trigger)"
        lines.append(f"### `{m.name}`")
        lines.append(f"- 描述:{m.description}")
        lines.append(f"- 触发词:{triggers}")
        if m.inputs:
            lines.append(f"- 入参格式:{m.inputs}")
        lines.append(f'- 调用方式:`run_skill(skill_name="{m.name}", args="<args>")`')
        lines.append("")

    return "\n".join(lines).rstrip()
