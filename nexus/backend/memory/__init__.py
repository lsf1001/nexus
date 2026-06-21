"""Nexus 记忆路径工厂。

严格按 deepagents 框架约定,记忆分两层:
- **用户级**:``~/.deepagents/AGENTS.md`` —— 跨重启持久化,所有用户共享
- **项目级**:``nexus/.deepagents/AGENTS.md`` —— 项目私有身份 / 规则

deepagents 的 :class:`MemoryMiddleware` 会按 ``memory=[...]`` 顺序加载
这些 AGENTS.md,拼接成 ``<agent_memory>...</agent_memory>`` 段注入 system prompt。
LLM 通过内置 ``edit_file`` 工具自更新这两个文件。
"""

from __future__ import annotations

from pathlib import Path


def make_memory_paths() -> tuple[Path, Path]:
    """返回 ``(user_md, project_md)`` 路径。

    Returns:
        ``(~/.deepagents/AGENTS.md, <project_root>/.deepagents/AGENTS.md)``
    """
    user_md = Path.home() / ".deepagents" / "AGENTS.md"
    project_md = Path(__file__).resolve().parent.parent.parent / ".deepagents" / "AGENTS.md"
    return user_md, project_md


__all__ = ["make_memory_paths"]
