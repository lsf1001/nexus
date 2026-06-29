"""langgraph checkpointer + store 工厂及其资源管理。

模块化拆分后,本模块集中承载:

- :data:`_CHECKPOINTER_CACHE` / :data:`_STORE_CACHE` — 模块级单例缓存
- :func:`_reset_checkpointer_cache` — 测试 fixture 用的清空 + 显式关连接
- :func:`_ensure_sqlite_checkpoint_tables` — sync 版 DDL 建表
- :func:`_close_async_conn_sync` / :func:`_run_coro_sync` / :func:`_make_async_saver_close_fn`
  — aiosqlite 在 sync 上下文中的连接管理三件套
- :func:`_create_store` — AsyncSqliteStore(默认)/ InMemoryStore(测试)工厂
- :func:`_create_checkpointer` — AsyncSqliteSaver(默认)/ MemorySaver(测试)工厂

WHY 单独成包:checkpointer + store 是 deepagents 跨 turn / 跨进程状态的
基础设施,集中一个文件便于统一处理资源生命周期(atexit 关闭 + 测试
fixture 隔离 + 锁顺序约束)。
"""

from __future__ import annotations

import asyncio as _asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)


# SqliteSaver 实例缓存:langgraph 0.6+ 的 SqliteSaver 持有 sqlite3.Connection,
# 必须在 agent 整个生命周期保持开。模块级单例 + atexit 关闭,避免每次
# ``_create_checkpointer`` 调用都开新连接把文件锁死。测试用 ``_reset_checkpointer_cache``
# 清缓存并关连接(否则 aiosqlite 后台线程让 pytest 退出挂死)。
#
# value 是 (saver, close_fn) 元组 — close_fn 负责同步释放 saver 持有的资源
# (aiosqlite connection),没有 close_fn 的(如 MemorySaver)用 None 占位。
_CHECKPOINTER_CACHE: dict[str, tuple[Any, Any | None]] = {}
_STORE_CACHE: dict[str, tuple[Any, Any | None]] = {}


def _reset_checkpointer_cache() -> None:
    """清空持久化资源缓存,并显式释放底层连接。

    WHY 1:pytest 跑多个 case 时如果用同一个 tmp db,旧 SqliteSaver 的 connection
    还拿着文件锁,新实例开不进去。给 fixture teardown 调一下,确保每个 case 独立。

    WHY 2(关键):AsyncSqliteSaver 持有的 aiosqlite.Connection 里有非 daemon
    后台线程。如果只 clear 缓存引用,线程不会退出,pytest 进程退出挂死。
    调 close_fn 关连接,后台线程收到 close 信号才会正常退出。
    """
    for _key, (_saver, close_fn) in list(_CHECKPOINTER_CACHE.items()):
        if close_fn is not None:
            try:
                close_fn()
            except Exception:  # noqa: BLE001 - 测试隔离,失败不致命
                pass
    _CHECKPOINTER_CACHE.clear()
    for _key, (_store, close_fn) in list(_STORE_CACHE.items()):
        if close_fn is not None:
            try:
                close_fn()
            except Exception:  # noqa: BLE001 - 关闭阶段尽力清理全部资源
                pass
    _STORE_CACHE.clear()


def _ensure_sqlite_checkpoint_tables(db_path: str) -> None:
    """确保 sqlite DB 里有 langgraph checkpoint 需要的表(checkpoints / writes)。

    WHY:AsyncSqliteSaver 自己也提供 async setup(),但我们要在 sync 上下文
    (daemon 线程 + _create_checkpointer 同步签名)里做这事。用同步版
    SqliteSaver.setup() 跑同一份 DDL,跟 AsyncSqliteSaver 共用同一 schema。
    已存在的业务表(sessions / messages)不会被影响(SqliteSaver 只 CREATE
    IF NOT EXISTS 自己那几个表)。
    """
    import sqlite3 as _sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = _sqlite3.connect(db_path)
    try:
        # SqliteSaver 接受一个 sync sqlite3.Connection,调 .setup() 走 DDL
        SqliteSaver(conn).setup()
    finally:
        conn.close()


def _close_async_conn_sync(conn: Any) -> None:
    """atexit 回调:同步关 aiosqlite 连接。

    WHY:aiosqlite.Connection.close 是 async 协程,直接 ``conn.close()`` 只会
    创建个未 await 的协程对象(会 RuntimeWarning)。在主线程里 ``asyncio.run``
    跑它的 close,触发后台线程退出 → 进程能正常结束。
    """
    try:
        _run_coro_sync(conn.close())
    except Exception:  # noqa: BLE001 - atexit 兜底,失败不致命
        pass


def _run_coro_sync(coro: Any) -> Any:
    """在 sync 上下文跑一个协程,兼容"已在 event loop 里"和"无 loop"两种场景。

    WHY:``asyncio.run(coro)`` 在已运行 loop 里调会抛
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``。
    Nexus 的 ``_create_checkpointer`` / ``_create_store`` 既要在 lifespan 启动期
    (无 loop,daemon 线程)调,也要在 HTTP 端点 ``POST /api/models/switch`` 里调
    (已在 uvicorn 的 loop 中)。两条路径必须共用同一段代码,所以统一用本 helper:

      - 有运行 loop → 在线程池工作线程中用 ``asyncio.run`` 执行,避免重入
        当前 loop。
      - 无运行 loop → ``asyncio.run`` 自建 loop,跑完即销毁。

    后者复用于 lifespan 启动 + 测试 fixture(都跑在 daemon 线程或 sync 测试里),
    前者复用于 HTTP 端点的 lazy 重建 agent(``switch_model`` / ``create_model`` /
    ``update_model`` 都触发)。

    Returns:
        协程的返回值。

    Raises:
        透传协程内部抛出的异常。
    """
    try:
        running_loop = _asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is None:
        return _asyncio.run(coro)

    # 同一线程不能对正在运行的 loop 调 run_until_complete。这里仅作为同步
    # 边界的防御性兼容;生产路由会把完整 Agent 构造推入 executor,通常不会
    # 进入此分支。
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexus-async-init") as executor:
        return executor.submit(_asyncio.run, coro).result()


def _make_async_saver_close_fn(conn: Any) -> Any:
    """构造 AsyncSqliteSaver 的 close 回调 — 给 _CHECKPOINTER_CACHE 用。

    WHY:test fixture 调 ``_reset_checkpointer_cache()`` 时要能主动关 aiosqlite
    连接,避免后台线程阻塞 pytest 退出。atexit 也注册了一份,但 fixture
    跑得更早更可控。
    """
    return lambda: _close_async_conn_sync(conn)


def _create_store() -> Any:
    """创建 langgraph Store — 给 ``/memories/`` 路由挂的 StoreBackend 用。

    选型:
      - ``NEXUS_STORE=memory`` → ``InMemoryStore``(in-process,单测用)
      - 默认 → ``AsyncSqliteStore``(写 ``~/.nexus/nexus.db``,跨进程持久)

    WHY 默认 Sqlite:LLM 写到 ``/memories/`` 路径的临时记忆(用户偏好 / 项目
    约定 / 中间结果)跨进程 / 跨重启存活,跟 checkpoint 同寿命。
    InMemoryStore 重启丢光,等于"用户偏好每次重启都得重写"。

    WHY AsyncSqliteStore:deepagents 0.6.8 的 StoreBackend 走 async 路径
    (astream_events),同步 SqliteStore 会抛 ``NotImplementedError``。
    """
    import os as _os

    backend = _os.environ.get("NEXUS_STORE", "sqlite").lower()
    nexus_home = Path(_os.environ.get("NEXUS_HOME", str(Path.home() / ".nexus"))).expanduser()
    db_path = _os.environ.get("NEXUS_DB_PATH") or str(nexus_home / "nexus.db")
    cache_key = f"{backend}::{db_path if backend == 'sqlite' else ''}"
    if cache_key in _STORE_CACHE:
        cached_store, _close_fn = _STORE_CACHE[cache_key]
        return cached_store

    if backend == "memory":
        from langgraph.store.memory import InMemoryStore

        store = InMemoryStore()
        _STORE_CACHE[cache_key] = (store, None)
        return store

    from langgraph.store.sqlite.aio import AsyncSqliteStore

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # AsyncSqliteStore.__init__ 调 ``asyncio.get_running_loop()`` 捕获循环
    # → 必须在 loop 内实例化。把 connect + 实例化都包进 ``asyncio.run`` 闭包,
    # loop 退出时 store 已持有 ``loop`` 引用(跟 AsyncSqliteSaver 一致)。
    import aiosqlite

    async def _build_async_store() -> Any:
        c = await aiosqlite.connect(db_path)
        store = AsyncSqliteStore(c)
        await store.setup()  # noqa: ERA001 - langgraph 公共 API
        # 显式 commit:setup() 内有 INSERT store_migrations(默认 deferred
        # 隔离级别),不 commit 持 WAL 写锁,后续 sync sqlite3 写同库直接
        # OperationalError: database is locked(busy_timeout 也救不了,持
        # 锁期间 sync 必失败)。这是 E2E 2026-06-25 真实 LLM 路径暴露的
        # 根因,务必保留。
        await c.commit()
        return store, c

    store, conn = _run_coro_sync(_build_async_store())
    # 注册 atexit 关连接(aiosqlite.Connection.close 是 async,走 asyncio.run)
    import atexit  # noqa: PLC0415 - 延迟到函数内 import,跟随 _create_checkpointer 风格

    atexit.register(_close_async_conn_sync, conn)
    _STORE_CACHE[cache_key] = (store, lambda: _close_async_conn_sync(conn))
    return store


def _create_checkpointer() -> Any:
    """创建 langgraph checkpointer(HITL 续流 / 跨 turn 状态必备)。

    选型:
      - ``NEXUS_CHECKPOINTER=memory`` → ``MemorySaver``(in-process,单测用)
      - 默认 → ``SqliteSaver``(写 ``~/.nexus/nexus.db``,跨进程存活)

    WHY:用户挂起 confirmation_request 后,如果后端进程意外退出,新进程拉起
    时必须能从 SqliteSaver 找回挂起的图状态,否则 Command(resume=...) 报错
    "No checkpoint found for thread_id",用户必须重发整个提示词。MemorySaver
    在进程重启后会丢光所有挂起态 → 用户体验灾难。
    """
    import atexit
    import os as _os

    backend = _os.environ.get("NEXUS_CHECKPOINTER", "sqlite").lower()
    nexus_home = Path(_os.environ.get("NEXUS_HOME", str(Path.home() / ".nexus"))).expanduser()
    db_path = _os.environ.get("NEXUS_DB_PATH") or str(nexus_home / "nexus.db")
    cache_key = f"{backend}::{db_path if backend == 'sqlite' else ''}"
    if cache_key in _CHECKPOINTER_CACHE:
        cached_saver, _close_fn = _CHECKPOINTER_CACHE[cache_key]
        return cached_saver

    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        saver: Any = MemorySaver()
        close_fn: Any | None = None
    elif backend == "sqlite":
        # 注意:必须用 ``AsyncSqliteSaver`` 而不是 ``SqliteSaver``——
        # agent.astream_events 是异步路径,同步 SqliteSaver 会在第一次 await
        # 触发 ``NotImplementedError: The SqliteSaver does not support asyn...``。
        # AsyncSqliteSaver 内部用 aiosqlite,checkpoint 仍落同一张表,
        # 跟 SqliteSaver 共享 sqlite 文件(同 schema)。
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # 走 ``SqliteSaver.setup()``(同步版)做 DDL 建表,跟 AsyncSqliteSaver
        # 共享同一 schema。这样我们能保持 ``_create_checkpointer`` 同步签名
        # (主流程在 daemon 线程跑)。
        _ensure_sqlite_checkpoint_tables(db_path)
        # AsyncSqliteSaver.__init__ 调 ``asyncio.get_running_loop()`` 捕获
        # 事件循环 → 必须在 loop 内实例化。把 connect + 实例化都包进
        # ``asyncio.run`` 闭包,loop 退出时 saver 已持有 ``loop`` 引用。
        import aiosqlite

        async def _build_async_saver() -> Any:
            c = await aiosqlite.connect(db_path)
            return AsyncSqliteSaver(c), c

        saver, conn = _run_coro_sync(_build_async_saver())
        # 进程退出时关连接(aiosqlite.Connection.close 是 async,走 asyncio.run)
        atexit.register(_close_async_conn_sync, conn)
        close_fn: Any | None = _make_async_saver_close_fn(conn)
    else:
        raise ValueError(f"未知 NEXUS_CHECKPOINTER={backend!r} (期望 'memory' 或 'sqlite')")

    _CHECKPOINTER_CACHE[cache_key] = (saver, close_fn)
    return saver
