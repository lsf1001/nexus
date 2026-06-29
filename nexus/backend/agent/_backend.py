"""DeepAgents filesystem backend 选型 + CompositeBackend 装配。

模块化拆分后,本模块集中承载:

- :func:`_select_filesystem_backend` — 根据 env 选
  ``FilesystemBackend`` / ``LocalShellBackend`` / ``LangSmithSandbox`` /
  ``ContextHubBackend``
- :func:`_create_backend` — 用 ``CompositeBackend`` 组合 fs_backend +
  ``StateBackend``(``/memories/`` 路由)+ 可选 ``StoreBackend``

WHY 单独成包:backend 选型 + 组合策略是 deepagents 集成的核心,但与
LLM / checkpointer / subagents 解耦,集中一个文件便于未来切换 sandbox
实现 / 调整 routes 优先级。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = __import__("logging").getLogger(__name__)


def _select_filesystem_backend(project_root: Path) -> Any:
    """根据 ``NEXUS_ENABLE_EXEC`` / ``NEXUS_EXEC_BACKEND`` env 选 backend。

    选项:
      - 默认(``NEXUS_ENABLE_EXEC`` 未设):``FilesystemBackend``(无 execute 工具)
      - ``NEXUS_ENABLE_EXEC=1``:``LocalShellBackend``(本地执行,无 HITL)
      - ``NEXUS_EXEC_BACKEND=langsmith``:``LangSmithSandbox``(远程沙箱,需 LANGSMITH_API_KEY)
      - ``NEXUS_EXEC_BACKEND=context_hub``:``ContextHubBackend``(LangSmith Hub repo)

    WHY env-gated:LangSmithSandbox / ContextHubBackend 都依赖 LangSmith 账号
    + 配额,生产默认关。只在本地开发 / 评测场景按需启用。

    ⚠️ 所有 execution backend 都跟 FilesystemPermission 互斥(deepagents 0.6.8
    框架限制,源码 ``filesystem.py:737-744``)。开启 = LLM 写源码不再触发
    HITL,源码侧由 confirmation 层兜底。
    """
    import os as _os

    backend_name = _os.environ.get("NEXUS_EXEC_BACKEND", "").lower()
    enable_exec = _os.environ.get("NEXUS_ENABLE_EXEC", "").lower() in {"1", "true", "yes"}

    if backend_name == "langsmith":
        from deepagents.backends.langsmith import LangSmithSandbox
        from langsmith.sandbox import Sandbox  # langsmith SDK 已装(deepagents 间接依赖)

        # LangSmithSandbox 需要一个已启动的 Sandbox 实例。SDK 不暴露
        # ``Sandbox.create`` 同步工厂,只有 ``reconnect(name)`` 拉已存在沙箱。
        # 真正启用流程:用户在 LangSmith 控制台建好 sandbox → 设
        # ``NEXUS_LANGSMITH_SANDBOX_NAME=xxx`` → Nexus 启动期 reconnect 拉回
        # 句柄。不在 Nexus 启动期阻塞拉新容器(避免配额 + 几十秒阻塞)。
        sandbox_name = _os.environ.get("NEXUS_LANGSMITH_SANDBOX_NAME")
        if not sandbox_name:
            raise ValueError("NEXUS_EXEC_BACKEND=langsmith 必须配 NEXUS_LANGSMITH_SANDBOX_NAME=<已建好的沙箱名>")
        sandbox = Sandbox.reconnect(name=sandbox_name)
        logger.warning("NEXUS_EXEC_BACKEND=langsmith:LangSmithSandbox 已启用,沙箱名=%s", sandbox.name)
        return LangSmithSandbox(sandbox=sandbox)

    if backend_name == "context_hub":
        from deepagents.backends.context_hub import ContextHubBackend

        # ContextHubBackend 用 LangSmith Client + Hub agent repo("owner/name" 或 "-/name")。
        # ``identifier`` 从 env 读;未设 → 抛错(强制用户显式配置)。
        identifier = _os.environ.get("NEXUS_CONTEXT_HUB_ID")
        if not identifier:
            raise ValueError("NEXUS_EXEC_BACKEND=context_hub 必须配 NEXUS_CONTEXT_HUB_ID='owner/name' 或 '-/name'")
        logger.warning("NEXUS_EXEC_BACKEND=context_hub:ContextHubBackend 已启用,hub=%s", identifier)
        return ContextHubBackend(identifier=identifier)

    if enable_exec:
        from deepagents.backends.local_shell import LocalShellBackend

        # inherit_env=True 让 LLM 看到 PATH 等环境变量(能找到 python / git 等)。
        # max_output_bytes=100_000 防 LLM 一次 dump 巨大日志。
        local = LocalShellBackend(
            root_dir=project_root,
            virtual_mode=False,
            inherit_env=True,
            max_output_bytes=100_000,
        )
        logger.warning(
            "NEXUS_ENABLE_EXEC=1:LocalShellBackend 已启用,LLM 可调 execute 工具跑 shell;"
            "FilesystemPermission 不生效(框架限制),源码 HITL 由用户在 confirmation 层兜底。"
        )
        return local

    from deepagents.backends.filesystem import FilesystemBackend

    return FilesystemBackend(root_dir=project_root, virtual_mode=False)


def _create_backend(project_root: Path, *, store: BaseStore | None = None):
    """创建组合 backend。

    使用 CompositeBackend 组合多个 backend:
    - FilesystemBackend: 真实文件系统访问(**默认,NEXUS_ENABLE_EXEC 未设**)
    - LocalShellBackend: 文件 + shell 命令执行(``NEXUS_ENABLE_EXEC=1`` 时)
    - LangSmithSandbox / ContextHubBackend: 远程沙箱(env-gated)
    - StateBackend: 状态管理(内存)
    - StoreBackend: 持久化存储(挂到 ``/memories/`` 路由)

    Args:
        project_root: 项目根目录。
        store: 持久化 store;非空时挂到 ``/memories/`` 路由供 LLM 跨会话读写。

    Note:
        ``virtual_mode=False`` 是必需的 — ``virtual_mode=True`` 会把绝对路径
        当作虚拟路径锚定到 ``project_root``,导致 ``~/.nexus/AGENTS.md``
        这种用户级记忆路径解析失败、MemoryMiddleware 静默
        跳过 → LLM 失去身份感。
        安全由 :class:`FilesystemPermission` + :class:`QualityGateMiddleware`
        在更上层兜底,此处不重复沙箱。

    ⚠️ **execution backend 警告**:
        LocalShellBackend / LangSmithSandbox / ContextHubBackend 让 LLM 可以
        跑 shell / 远程代码。deepagents 0.6.8 的 FilesystemMiddleware
        **不支持同时配 permissions 和 execution backend**(框架会主动禁用
        permissions,源码 ``filesystem.py:737-744``)。开启 = LLM 写源码不再
        触发 HITL,由用户自负风险。建议只在本地开发 / CI 测试环境开启,
        生产禁用。
    """
    from deepagents.backends.composite import CompositeBackend
    from deepagents.backends.state import StateBackend
    from deepagents.backends.store import StoreBackend

    fs_backend = _select_filesystem_backend(project_root)

    routes: dict[str, Any] = {
        ".nexus/state/": StateBackend(),
    }
    if store is not None:
        routes["/memories/"] = StoreBackend(store=store)

    return CompositeBackend(
        default=fs_backend,
        routes=routes,
    )
