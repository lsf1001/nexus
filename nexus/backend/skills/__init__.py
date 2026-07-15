"""``nexus.backend.skills``:运行时 SKILL.md 加载器。

用户在 ``~/.nexus/skills/<name>/SKILL.md`` 放的 markdown 文件会被
lifespan 启动时自动扫描,frontmatter 解析为 :class:`SkillManifest`,
存入 module-level :data:`REGISTRY`,LLM 触发 ``run_skill`` 工具时
按 entrypoint 调用。

参考:Claude Code 的 ``.claude/skills/`` 机制(单 md 文件 + entrypoint)。
"""

from __future__ import annotations

from .loader import REGISTRY, SKILLS_DIR, parse_skill_md, render_skills_for_prompt, scan_skills_dir
from .schema import SkillManifest

__all__ = [
    "REGISTRY",
    "SKILLS_DIR",
    "SkillManifest",
    "parse_skill_md",
    "render_skills_for_prompt",
    "scan_skills_dir",
]
