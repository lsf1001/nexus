"""应用全局不可变状态 + lifespan 装配入口。

WHY 抽 AppState: 主 ``main.py`` lifespan 直接把 agent / mcp_tools /
main_loop / db_conn 等绑到 ``app.state`` 或 module-global。多个 handler
并发改 module-global 会引入生命周期泄漏 / 竞态。改用 ``AppState``
frozen dataclass 后:
  - 启动期一次性创建,所有 handler 拿 ``request.app.state.app_state``
  - frozen + MappingProxyType 防止运行期意外 mutate
  - 单测可独立构造(无须 lifespan 启动)

``init_app_state()`` 把 lifespan 内 init_db / projects 迁移 / skill 扫描 /
reload_system_prompt 等独立子任务抽到本文件。``main.py`` 的 ``lifespan``
只剩 ~30 行:调 ``init_app_state`` + 派生 module-global ref + 装配 Gateway。
WHY: main.py 文件总行数受 spec §3.6 ≤800 行硬约束。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppState:
    """Lifespan 创建的全局不可变状态。

    字段:
      - main_loop: 启动期 asyncio 主循环(WS handler 跨线程桥接用)
      - agents: 名称 → CompiledStateGraph 的不可变 mapping
      - mcp_tools: MCP 工具 tuple(不可 append)
      - db_conn: 数据库连接句柄(aiosqlite 或 sqlite3)
      - started_at: 启动时间戳(epoch 秒)
    """

    main_loop: asyncio.AbstractEventLoop
    agents: MappingProxyType[str, Any]
    mcp_tools: tuple[Any, ...]
    db_conn: Any
    started_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """frozen 字段类型强制: dict → MappingProxyType,list → tuple。

        WHY: dataclass 字段类型不强制,调用方传 dict 时 Python 不会自动
        转 MappingProxyType → spec §3.2 行为保证失效。这里强制转换,
        保证 ``state.agents`` 任何来源下都是不可变 mapping。
        """
        if not isinstance(self.agents, MappingProxyType):
            object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))
        if not isinstance(self.mcp_tools, tuple):
            object.__setattr__(self, "mcp_tools", tuple(self.mcp_tools))


async def init_app_state(app: Any) -> AppState:
    """Lifespan 启动期初始化,创建并返回 :class:`AppState` 实例。

    包含子任务:
      1. 取主事件循环
      2. ``init_db()`` (PRAGMA + 自动建表)
      3. 默认 Project 自动迁移(SPEC §4.2)
      4. 恢复上次激活的 Project
      5. 扫描运行时 skills(失败不阻断启动)
      6. ``reload_system_prompt()`` 清缓存

    WHY 抽到本文件:main.py 文件总行数受限(≤800),把这些与 module-global
    无关的独立子任务集中,主流程只剩 Gateway/ChannelRegistry 装配。
    """
    main_loop = asyncio.get_running_loop()
    # 初始化数据库
    from .db import init_db

    init_db()
    # Round 1 SPEC §4.2: 默认 Project 自动迁移 — DB 初始化后立即跑,
    # 确保 sessions.project_id 不为 NULL,后续 agent 构造能立即拿到上下文。
    try:
        from .projects.storage import (
            ensure_default_project,
            migrate_sessions_to_default,
        )

        ensure_default_project()
        migrate_sessions_to_default()
    except (OSError, sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
        # 环境异常(磁盘满 / 权限 / FK 半迁移状态):降级 warning + 继续启动,
        # 让旧 Nexus 安装(没有 ~/Nexus/projects/ 目录)能成功跑起来。
        # 真正的系统错误继续向外抛,例如后续 SPEC §5.1 严格化时直接 raise。
        logger.warning("[projects] 默认 Project 迁移失败(继续启动): %s", exc, exc_info=True)
    # 恢复上次激活的 Project；必须在默认 Project 创建后验证 DB 行是否存在。
    try:
        from .agent._system_prompt import set_active_project_id
        from .db import get_db
        from .projects.storage import read_active_project_id

        active_project_id = read_active_project_id()
        if active_project_id is not None:
            with get_db() as conn:
                project_exists = conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?",
                    (active_project_id,),
                ).fetchone()
            if project_exists is not None:
                set_active_project_id(active_project_id)
            else:
                logger.warning("[projects] active Project 不存在,跳过恢复: %s", active_project_id)
    except (OSError, json.JSONDecodeError, sqlite3.Error) as exc:
        logger.warning("[projects] active Project 恢复失败(继续启动): %s", exc, exc_info=True)
    # 扫描运行时 skills(2026-07-15 引入)
    # WHY init_db 之后:skill 加载失败不应阻断 DB 初始化。
    # WHY 单独 try-except:用户 ~/.nexus/skills/ 损坏不该阻断整个启动。
    try:
        from .skills import scan_skills_dir

        scan_skills_dir()
    except Exception as e:  # noqa: BLE001 — 兜底任意扫描异常,不阻断启动
        logger.warning("[skills] scan 失败,继续启动(无 skill 可用): %s", e, exc_info=True)
    # 清空 system prompt 缓存,下次 get_system_prompt 会拼上新加载的 skills
    from .agent._system_prompt import reload_system_prompt

    reload_system_prompt()
    # MCP 加载延后到 agent 首次构造时(省 0.5-3s)
    # Agent 懒构造:首次 WS 消息 / setup 完成时走 _ensure_agent_ready()。
    # 期间 /health / REST 路由正常工作。
    return AppState(
        main_loop=main_loop,
        agents=MappingProxyType({}),
        mcp_tools=(),
        db_conn=None,
    )
