"""回归测试:classify_intent 必须在 5s 内超时兜底 chitchat,不阻塞主流程。

WHY 2026-06-28:agnes API 实际响应 16s+,意图分类本应 8s 超时
但日志显示 latency=16821ms,说明 asyncio.wait_for 没生效。
本测试用 mock LLM 强制 sleep 10s,验证 5s 后返回 chitchat 而不是阻塞。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from nexus.backend.intent.router import classify_intent


class _HangingLLM:
    """模拟永远不会自然完成的 LLM 调用。"""

    def bind_tools(self, tools: list) -> _HangingLLM:
        return self

    async def ainvoke(self, messages: list) -> Any:  # noqa: ARG002
        await asyncio.sleep(30)  # 永远不返回
        return None  # unreachable


@pytest.mark.asyncio
async def test_intent_classify_timeout_returns_chitchat() -> None:
    """5s 内必须兜底 chitchat,不能阻塞超过 5.5s。"""
    llm = _HangingLLM()
    start = time.monotonic()
    intent = await classify_intent(llm, "test message")
    elapsed = time.monotonic() - start

    assert intent == "chitchat", f"超时应兜底 chitchat,实际 {intent}"
    assert elapsed < 5.5, f"超时硬限 5s,实际 {elapsed:.2f}s 仍在阻塞"


@pytest.mark.asyncio
async def test_intent_classify_normal_path_unchanged() -> None:
    """正常路径(LLM 1s 内返回 tool_call)必须正常工作。"""

    class _FastLLM:
        def bind_tools(self, tools: list) -> _FastLLM:
            return self

        async def ainvoke(self, messages: list) -> Any:
            await asyncio.sleep(0.1)
            return type("R", (), {"tool_calls": [{"name": "route_task_execute"}]})()

    intent = await classify_intent(_FastLLM(), "test")
    assert intent == "task"


@pytest.mark.asyncio
async def test_intent_classify_timeout_uses_asyncio_timeout() -> None:
    """必须用 asyncio.timeout 上下文管理器(更可靠),禁止 wait_for。

    WHY:wait_for 在 httpx connection 挂起时无法可靠传播 cancel,改用
    asyncio.timeout 上下文管理器是 Task 4 的核心契约。
    """
    import inspect

    source = inspect.getsource(classify_intent)
    assert "asyncio.timeout" in source, "classify_intent 必须用 asyncio.timeout 上下文管理器"
    assert "asyncio.wait_for" not in source, "禁止 asyncio.wait_for(2026-06-28 实测 cancel 不可靠)"
