"""Nexus Agent 模块包:把 ``agent.py``(1080 行)拆成职责单一的子模块。

模块布局:

- :mod:`._system_prompt` — 系统提示词构建 + 缓存 + 项目根目录解析
- :mod:`._llm_factory` — LLM 工厂 + 主题研究模式判断
- :mod:`._checkpoint` — langgraph checkpointer + store 工厂及其资源管理
- :mod:`._backend` — DeepAgents filesystem backend 选型 + 装配
- :mod:`._subagents` — SubAgent 工厂(内置 + env-gated)
- :mod:`._agent_builder` — 主 Agent 工厂 ``create_agent``(组装入口)

WHY 拆分:旧 ``agent.py`` 单文件 1080 行超 python_project.md §1.2 上限
(单文件 ≤ 800 行)。拆分后每模块均 ≤ 300 行,职责清晰,后续单独修改某
一职责不会引发 merge 冲突。本包对外保持与旧文件完全一致的公共 API:

    from nexus.backend.agent import create_agent
    from nexus.backend.agent import _reset_checkpointer_cache
    from nexus.backend.agent import get_llm
    from nexus.backend.agent import is_research_topic
    from nexus.backend.agent import build_interrupt_on_for_agent
"""

from __future__ import annotations

# 重新导出所有公共符号,保持与旧 agent.py 一致的导入路径
from ._agent_builder import create_agent
from ._backend import _create_backend, _select_filesystem_backend
from ._checkpoint import (
    _CHECKPOINTER_CACHE,
    _STORE_CACHE,
    _close_async_conn_sync,
    _create_checkpointer,
    _create_store,
    _ensure_sqlite_checkpoint_tables,
    _make_async_saver_close_fn,
    _reset_checkpointer_cache,
    _run_coro_sync,
)
from ._llm_factory import get_llm, is_research_topic
from ._subagents import (
    _load_async_subagent_specs,
    _load_compiled_subagent_specs,
    build_interrupt_on_for_agent,
    create_subagents,
)
from ._system_prompt import (
    _CACHED_PROMPT,
    _build_system_prompt,
    get_project_root,
    get_system_prompt,
    reload_system_prompt,
)

__all__ = [
    # 主入口
    "create_agent",
    # 系统提示词
    "_build_system_prompt",
    "get_system_prompt",
    "reload_system_prompt",
    "_CACHED_PROMPT",
    "get_project_root",
    # LLM 工厂
    "get_llm",
    "is_research_topic",
    # Checkpointer / Store
    "_reset_checkpointer_cache",
    "_ensure_sqlite_checkpoint_tables",
    "_close_async_conn_sync",
    "_run_coro_sync",
    "_make_async_saver_close_fn",
    "_create_store",
    "_create_checkpointer",
    "_CHECKPOINTER_CACHE",
    "_STORE_CACHE",
    # Backend
    "_select_filesystem_backend",
    "_create_backend",
    # Subagents
    "build_interrupt_on_for_agent",
    "create_subagents",
    "_load_compiled_subagent_specs",
    "_load_async_subagent_specs",
]
