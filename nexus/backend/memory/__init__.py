"""Nexus 记忆路径工厂。

记忆分两层:
- **用户级**:``~/.nexus/AGENTS.md`` —— 跨重启持久化,只服务 Nexus
- **项目级**:``nexus/.deepagents/AGENTS.md`` —— 项目私有身份 / 规则

WHY 不放 ``~/.deepagents/``:deepagents 框架默认用 ``~/.deepagents/``,
但那是通用框架约定,跨项目共享用户偏好。Nexus 是产品不是工具,
用户数据必须跟产品绑,放 ``~/.nexus/`` 防污染也防被其它 deepagents
项目读到。

deepagents 的 :class:`MemoryMiddleware` 按 ``memory=[...]`` 顺序加载
这两个 AGENTS.md,拼成 ``<agent_memory>...</agent_memory>`` 注入 system prompt。
LLM 通过内置 ``edit_file`` 工具自更新。
"""

from __future__ import annotations

from pathlib import Path


def make_memory_paths() -> tuple[Path, Path]:
    """返回 ``(user_md, project_md)`` 路径。

    Returns:
        ``(~/.nexus/AGENTS.md, <project_root>/.deepagents/AGENTS.md)``
    """
    user_md = Path.home() / ".nexus" / "AGENTS.md"
    project_md = Path(__file__).resolve().parent.parent.parent / ".deepagents" / "AGENTS.md"
    return user_md, project_md


__all__ = ["make_memory_paths"]
