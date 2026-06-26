"""Nexus 用户级长期记忆路径。

定位:Nexus 是个人智能助理(对标 OpenClaw),用户数据目录**只有一个** —— ``~/.nexus/``。
LLM 跨会话持久化的偏好 / 事实 / 规则都落在 ``~/.nexus/AGENTS.md``,由
deepagents :class:`MemoryMiddleware` 自动加载并以 ``<agent_memory>...</agent_memory>``
段注入 system prompt,LLM 通过内置 ``edit_file`` / ``write_file`` 自更新。

WHY 不放 ``~/.deepagents/``:deepagents 框架默认用 ``~/.deepagents/``,
那是通用框架约定,跨项目共享用户偏好。Nexus 是产品不是工具,
用户数据必须跟产品绑,放 ``~/.nexus/`` 防污染也防被其它 deepagents
项目读到。

历史形态(已删除):
  - 早先版本在 ``nexus/.deepagents/AGENTS.md`` 维护项目级身份 / 规则。
    这是开发期"项目级 CLAUDE.md"思维的产物,跟个人助理定位冲突 —— 用户安装
    DMG 后没有"项目"概念,DMG 内不该带身份文件。已删除,产品身份改为
    hardcode 在 :func:`nexus.backend.agent._build_system_prompt`。
"""

from __future__ import annotations

from pathlib import Path

# Nexus 用户级长期记忆文件唯一路径。
USER_MEMORY_PATH: Path = Path.home() / ".nexus" / "AGENTS.md"


def make_memory_paths() -> tuple[Path]:
    """返回 Nexus 用户级长期记忆路径。

    历史接口返回 ``(user_md, project_md)`` 双元素元组,project_md 是
    ``nexus/.deepagents/AGENTS.md``。2026-06 OpenClaw 定位重设计后只剩
    user_md,签名降为单元素 tuple 以便 ``for p in make_memory_paths()`` 类
    调用方零感知。

    Returns:
        单元素 ``(USER_MEMORY_PATH,)``。
    """
    return (USER_MEMORY_PATH,)


__all__ = ["USER_MEMORY_PATH", "make_memory_paths"]
