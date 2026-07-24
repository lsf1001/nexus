"""Project 文件系统 + 默认 Project 迁移 — SPEC §4.2。

WHY 单文件:把目录布局 / AGENTS.md 拷贝 / 软链创建集中在一个地方,
默认 Project 迁移 + 用户新建 Project 共用同一组 helper,避免散落。
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import time
from pathlib import Path

from ..config import _get_nexus_home
from ..db import get_db

logger = logging.getLogger(__name__)


def _projects_root() -> Path:
    """所有 Project 目录的父目录 ~/Nexus/projects/。

    WHY 走 _get_nexus_home().parent:NEXUS_HOME 可在测试 / 容器 / 自定义安装里改写,
    必须让 projects 根跟着走,避免测试 fixture 伸到开发者 home 实际清盘。
    默认 macOS 下 .parent == ~/,所以展开为 ~/Nexus/projects/。
    """
    return _get_nexus_home().parent / "Nexus" / "projects"


def default_project_path() -> Path:
    """默认 Project 目录绝对路径 ~/Nexus/projects/default/。"""
    return _projects_root() / "default"


def read_active_project_id() -> str | None:
    """读取持久化的 active Project id；文件缺失或内容无效时返回 None。"""
    active_file = _get_nexus_home() / "active_project.json"
    if not active_file.exists():
        return None
    payload = json.loads(active_file.read_text(encoding="utf-8"))
    project_id = payload.get("active_project_id")
    return project_id if isinstance(project_id, str) and project_id else None


def _copy_agents_md(src: Path, dst: Path) -> None:
    """把 src/AGENTS.md 拷到 dst/AGENTS.md。幂等:dst 已存在则跳过(保护用户编辑)。

    WHY copy2 不是 symlink:SPEC §4.2 决策表明确"AGENTS.md 拷贝非软链" —
    用户编辑 ~/Nexus/projects/default/AGENTS.md 不应回写到 ~/.nexus/AGENTS.md,
    否则会污染用户级记忆。
    """
    if dst.exists():
        return  # 保护用户已编辑的 dst,任何情况下不再覆写
    if src.exists():
        shutil.copy2(src, dst)
    else:
        dst.write_text(
            "# 默认 Project\n\n"
            "此 Project 由 Nexus 启动时自动创建。你可以自由编辑本文件,\n"
            "修改只影响当前 Project 内的会话上下文,不会影响 ~/.nexus/AGENTS.md。\n",
            encoding="utf-8",
        )


def _link_skills(project_path: Path) -> None:
    """把 project_path/skills 创建为软链 → ~/.nexus/skills/。

    WHY 软链:避免内容重复;用户~/.nexus/skills/ 里的 skill 立即对默认 Project 生效,
    无需复制。SPEC §5.3 决策"软链向后兼容"。

    WHY FileExistsError 容错:首次启动后 ~/.nexus/skills/ 可能是真实目录(用户手动建),
    symlink_to 会抛 FileExistsError,降级保留现状不阻断。
    其余 OSError 透传给 main.py lifespan 顶层 catch,转 RuntimeError,符合 SPEC §5.1。
    """
    link = project_path / "skills"
    target = _get_nexus_home() / "skills"
    if link.is_symlink():
        return  # 已是软链,幂等
    if link.exists():
        logger.warning("[projects] %s 已存在但不是软链,跳过链接创建", link)
        return
    target.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileExistsError):
        link.symlink_to(target)


def _init_mcp_json(project_path: Path) -> None:
    """创建 project_path/mcp.json 默认配置(空 enabled servers)。"""
    cfg = project_path / "mcp.json"
    if cfg.exists():
        return
    cfg.write_text(
        json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_default_project() -> None:
    """确保默认 Project(default)存在 — SPEC §4.2。

    幂等:可重入。已存在时所有写操作跳过(避免覆盖用户已编辑的 AGENTS.md)。
    """
    path = default_project_path()
    path.mkdir(parents=True, exist_ok=True)
    _copy_agents_md(_get_nexus_home() / "AGENTS.md", path / "AGENTS.md")
    _link_skills(path)
    _init_mcp_json(path)

    # DB 写入:upsert。已存在则不改 display_name / description。
    now = int(time.time() * 1000)
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM projects WHERE id='default'").fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO projects (id, name, display_name, path, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "default",
                    "default",
                    "默认项目",
                    str(path),
                    "Nexus 启动时自动创建;所有现有会话归属此处。",
                    now,
                    now,
                ),
            )
            logger.info("默认 Project 已创建: %s", path)
        else:
            logger.debug("默认 Project 已存在: %s", path)


def migrate_sessions_to_default() -> None:
    """把所有 project_id IS NULL 的 sessions 迁到 default — SPEC §4.2。

    单条 UPDATE 事务,失败回滚(由 get_db 的 contextmanager 兜底)。
    已带 project_id 的 sessions **不**覆写(测试覆盖)。
    不动 updated_at:保持原值,格式统一由 db.py 现有写入器(isoformat)负责。
    """
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE sessions SET project_id='default' WHERE project_id IS NULL OR project_id=''",
        )
        count = cursor.rowcount
    if count:
        logger.info("migrated %d sessions to default project", count)
