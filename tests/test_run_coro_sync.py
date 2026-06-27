"""``nexus.backend.agent._run_coro_sync`` 的契约测试。

覆盖三类场景:
  1. 无运行 loop(同步调用)→ ``asyncio.run`` 路径,协程返回值透传。
  2. 有运行 loop(async 上下文调)→ ``loop.run_until_complete`` 路径,不能
     抛 ``RuntimeError: asyncio.run() cannot be called from a running event loop``。
  3. 协程内部抛出的异常透传,不被 helper 吞掉。

WHY:2026-06-27 E2E 暴露 ``POST /api/models/switch`` 触发 500 Internal Server Error,
根因是 ``_create_checkpointer`` 在 uvicorn 已运行 event loop 的线程里调
``asyncio.run(coro)`` → RuntimeError。修复:加 ``_run_coro_sync`` helper 检测
loop 状态。Lifespan 启动期无 loop,HTTP 端点有 loop,两条路径必须共用 helper。
"""

from __future__ import annotations

import asyncio

import pytest

from nexus.backend.agent import _run_coro_sync


class TestRunCoroSyncNoLoop:
    """无运行 loop 时走 ``asyncio.run`` 路径(sync 上下文)。"""

    def test_returns_coro_value(self) -> None:
        async def coro() -> str:
            return "ok"

        assert _run_coro_sync(coro()) == "ok"

    def test_propagates_coro_exception(self) -> None:
        async def coro() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_coro_sync(coro())


class TestRunCoroSyncInsideLoop:
    """已在 event loop 里时走 ``loop.run_until_complete`` 路径(async 上下文)。

    之前的 bug:这里调 ``asyncio.run`` 会抛 ``RuntimeError``。本测试保证
    helper 能识别出运行中的 loop 并走正确路径,不会污染事件循环。
    """

    @pytest.mark.asyncio
    async def test_returns_coro_value_from_inside_loop(self) -> None:
        async def coro() -> int:
            await asyncio.sleep(0)
            return 42

        # 如果 helper 没检测 loop 状态,这一行会抛 RuntimeError
        result = _run_coro_sync(coro())
        assert result == 42

    @pytest.mark.asyncio
    async def test_does_not_raise_running_loop_error(self) -> None:
        """明确守卫:不能抛 ``asyncio.run() cannot be called from a running event loop``。"""

        async def coro() -> None:
            await asyncio.sleep(0)

        # 关键断言:这里不应该抛 RuntimeError。如果抛了,helper 检测 loop 状态失败。
        _run_coro_sync(coro())

    @pytest.mark.asyncio
    async def test_propagates_coro_exception_from_inside_loop(self) -> None:
        async def coro() -> None:
            raise RuntimeError("inner")

        with pytest.raises(RuntimeError, match="inner"):
            _run_coro_sync(coro())

    @pytest.mark.asyncio
    async def test_loop_survives_helper_invocation(self) -> None:
        """Helper 跑完后,当前 loop 仍能正常工作(没被 ``asyncio.run`` 销毁)。"""

        async def coro() -> None:
            await asyncio.sleep(0)

        _run_coro_sync(coro())
        # 紧接着再跑一个 sleep,确认 loop 没坏
        await asyncio.sleep(0)
        assert not asyncio.get_running_loop().is_closed()


class TestRunCoroSyncReplayUseCase:
    """复现 ``POST /api/models/switch`` 真实场景:在 uvicorn event loop 内同步调用
    本来需要异步初始化的资源(checkpointer / store)。

    WHY:``switch_model`` 调 ``_create_agent_with_model`` → ``create_agent`` →
    ``_create_checkpointer`` → ``_asyncio.run(_build_async_saver())``。整个调用栈
    在 uvicorn worker 线程的运行中 loop 里。本测试直接复现这一栈,确保
    ``_run_coro_sync`` 在这种场景下不会炸。
    """

    @pytest.mark.asyncio
    async def test_async_sqlite_saver_construction_inside_loop(self) -> None:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async def build() -> tuple[AsyncSqliteSaver, object]:
            import aiosqlite

            c = await aiosqlite.connect(":memory:")
            return AsyncSqliteSaver(c), c

        saver, conn = _run_coro_sync(build())
        try:
            assert isinstance(saver, AsyncSqliteSaver)
        finally:
            # 显式关连接,清掉 aiosqlite 后台线程(否则 pytest 退出挂)
            _run_coro_sync(conn.close())  # type: ignore[attr-defined]
