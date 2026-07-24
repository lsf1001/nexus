"""per-project skills 扫描 — SPEC §4.4 / §5.3。

关键设计:
    Skills 是包含 ``SKILL.md`` 的目录,deepagents 用它在 system prompt
    注入可用 skills 列表(详见 :mod:`nexus.backend.agent._system_prompt`)。

    与已有 :mod:`nexus.backend.skills.loader.scan_skills_dir` 区别:
      - scan_skills_dir 扫 ``~/.nexus/skills/``,解析 frontmatter → SkillManifest,
        塞到 REGISTRY(进程单例),供 system_prompt 渲染。
      - 本模块 ``list_skills`` 按 project_id 扫,返回轻量 dict 给 REST API 用,
        不写 REGISTRY、不走 Pydantic 校验。

WHY 不重写 scan_skills_dir:那是 lifespan 启动路径,且 SkillManifest 校验在
    system prompt 拼装时是必需的(避免损坏文件拖累整个 agent);REST API
    只需 list 形态,简单可靠即可。

为什么按 inode 去重(SPEC §5.3):
    默认 project 的 ``~/Nexus/projects/default/skills`` 是软链 →
    ``~/.nexus/skills/``,同一个物理目录经两条路径访问,API 必须
    返回 1 条,否则 Skills 面板会重复渲染同一文件。

失败容忍:
    目录不存在 / SKILL.md 损坏 → 空 list,**不抛**。
    skills 是"best-effort"特性,绝不能阻断 agent 构造或 REST 调用。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import _get_nexus_home
from .storage import _projects_root

logger = logging.getLogger(__name__)


def _resolve_skills_root(project_id: str) -> Path | None:
    """拿 project 对应 skills 目录的真实路径。

    - ``default`` project → ``~/.nexus/skills/``(向后兼容)
    - 其它 project → ``~/Nexus/projects/<name>/skills/``
    - 不存在 → ``None``

    WHY 默认 project 不走 ``~/Nexus/projects/default/skills``:
        它的真实路径就是 ``~/.nexus/skills`` 软链展开后的目标,
        直接读目标可避免"对软链目录 iterdir() 再二次 resolve"的
        重复路径计算,也避免 inode 比较的潜在误判。
    """
    if project_id == "default":
        target = _get_nexus_home() / "skills"
        if not target.exists():
            return None
        return target.resolve()
    proj = _projects_root() / project_id
    skills = proj / "skills"
    # 软链或真目录都接受:resolve 后比较 inode 即可去重
    if not skills.exists() and not skills.is_symlink():
        return None
    return skills.resolve()


def _scan(skills_root: Path) -> list[dict]:
    """扫 skills_root 下所有含 ``SKILL.md`` 的子目录,按 inode 去重。

    Returns:
        list of ``{"name": str, "path": str, "source": "local" | "project"}``,
        按 name 升序排序(确定性输出,便于 prompt diff / 面板渲染稳定)。
    """
    seen_inodes: set[int] = set()
    out: list[dict] = []
    if not skills_root.is_dir():
        return out
    for entry in skills_root.iterdir():
        # 软链目录在 Linux 上 is_dir() 可能 False(目标存在才 True);保险起见两者都接受
        if not (entry.is_dir() or entry.is_symlink()):
            continue
        try:
            resolved = entry.resolve(strict=False)
        except OSError:
            # 软链悬空 / 权限拒 → 跳过
            continue
        if not (resolved / "SKILL.md").exists():
            continue
        try:
            inode = resolved.stat().st_ino
        except OSError:
            continue
        if inode in seen_inodes:
            # SPEC §5.3:同 inode 不同路径 → 视为同一 skill,只列一次
            continue
        seen_inodes.add(inode)
        out.append(
            {
                "name": entry.name,
                "path": str(resolved),
                "source": "project" if entry.is_symlink() else "local",
            }
        )
    out.sort(key=lambda s: s["name"])
    return out


def list_skills(project_id: str) -> list[dict]:
    """列出 project_id 下的可用 skills。

    失败 / 不存在 → 空 list(绝不抛,避免阻断 agent 构造)。

    Args:
        project_id: Project 的 id(``default`` / 用户新建的 slug)。

    Returns:
        list of ``{"name": str, "path": str, "source": "local" | "project"}``
    """
    root = _resolve_skills_root(project_id)
    if root is None:
        logger.debug("Project %s 无 skills 目录", project_id)
        return []
    try:
        return _scan(root)
    except OSError as exc:
        logger.warning("scan skills for %s failed: %s", project_id, exc)
        return []


def skills_root_for_env(project_id: str) -> Path | None:
    """暴露给 system_prompt 注入用 — 返回真实 path,可能含多个 skill 子目录。

    WHY 与 ``list_skills`` 分开:system_prompt 拼装关心"目录在哪"
    (用于读 SKILL.md 内容),REST API 关心"列出哪些 skill",
    两者的下钻粒度不同。
    """
    return _resolve_skills_root(project_id)
