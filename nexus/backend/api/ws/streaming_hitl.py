"""HITL 流式事件处理 — 从 streaming.py 拆出。

WHY 单独成包:streaming.py 累积到 881 行,超 §1.2 800 上限。HITL 三个 handler
逻辑独立(GraphInterrupt 兜底 + state.interrupts drain + confirmation 帧发出),
抽到独立模块,主模块聚焦 chunk / thinking / tool 事件分发。

被 streaming.py 的 :func:`_consume_astream_events` 调用,Handler 接收 ws + session
+ interrupts 元组,职责单一。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from .finalize import _serialize_hitl_request

__all__ = [
    "_emit_hitl_confirmation_frames",
    "_handle_graph_interrupt",
    "_drain_pending_hitl_interrupts",
]


logger = logging.getLogger(__name__)


async def _handle_graph_interrupt(
    websocket: WebSocket,
    session_id: str,
    gi: Any,
    last_event_id: int,
    emitted_chunk_text: str,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None]:
    """GraphInterrupt 异常:发 confirmation_request 帧并挂起。

    WHY 理论路径:langgraph 0.6+ 实际在 _loop.__exit__ 主动 suppress,
    见 :func:`_drain_pending_hitl_interrupts` fallback。
    """
    interrupts = gi.args[0] or ()  # GraphInterrupt(interrupts=[...])
    logger.info(
        "WS HITL GraphInterrupt 捕获: session=%s, interrupts=%d",
        session_id,
        len(interrupts),
    )
    last_event_id = await _emit_hitl_confirmation_frames(websocket, session_id, interrupts, last_event_id)
    pending: tuple | None = tuple(interrupts) if interrupts else None
    # WHY 不写 _session_hitl_state:挂起 interrupt 已经存到 checkpoint 的
    # ``__interrupt__`` channel,续流时通过 ``agent.aget_state(thread_id)``
    # 读回,无需进程内缓存(多 worker 部署天然兼容)。
    return last_event_id, emitted_chunk_text, False, None, pending


async def _drain_pending_hitl_interrupts(
    agent: Any,
    websocket: WebSocket,
    session_id: str,
    astream_kwargs: dict[str, Any],
    last_event_id: int,
    emitted_chunk_text: str,
) -> tuple[int, str, tuple | None]:
    """langgraph 0.6+:从 ``agent.aget_state(config).interrupts`` 读 pending interrupt。

    Pregel._loop.__exit__ 会主动 ``return True`` 抑制 GraphInterrupt(把
    interrupt 信息存到 checkpoint 的 ``__interrupt__`` channel),所以
    ``agent.astream_events`` 不抛异常而正常结束。HITL 状态只能从
    ``agent.get_state(config).interrupts`` 读取 — langgraph 0.6+ 暴露
    pending interrupt 的官方 API。

    WHY ``agent.aget_state``(不是 ``get_state``):agent 用 AsyncSqliteSaver
    时,``checkpointer.aget_tuple`` 是 async;同步 ``get_state`` 内部
    ``checkpointer.get_tuple(config)`` 在 AsyncSqliteSaver 上拿到的是
    coroutine(没 await),触发 "coroutine 'aget_tuple' was never awaited"
    warning,interrupts 永远空。

    Returns:
        ``(last_event_id, emitted_chunk_text, pending_interrupts_or_none)``:
        ``pending_interrupts_or_none`` 为 ``None`` 时表示无 HITL 挂起,继续
        主流程。
    """
    try:
        snapshot = await agent.aget_state(astream_kwargs["config"])
        pending_interrupts = tuple(snapshot.interrupts) if snapshot.interrupts else ()
    except Exception as gs_exc:  # noqa: BLE001 — 边界统一收口
        logger.warning("WS get_state 失败,跳过 HITL state 兜底: %s", gs_exc, exc_info=True)
        pending_interrupts = ()
    if not pending_interrupts:
        return last_event_id, emitted_chunk_text, None
    logger.info(
        "WS HITL state.interrupts 捕获: session=%s, interrupts=%d",
        session_id,
        len(pending_interrupts),
    )
    last_event_id = await _emit_hitl_confirmation_frames(websocket, session_id, pending_interrupts, last_event_id)
    return last_event_id, emitted_chunk_text, pending_interrupts


async def _emit_hitl_confirmation_frames(
    websocket: WebSocket,
    session_id: str,
    interrupts: Any,
    last_event_id: int,
) -> int:
    """把 langgraph Interrupt 序列翻成 confirmation_request 帧。

    共用于 :func:`_handle_graph_interrupt` 和 :func:`_drain_pending_hitl_interrupts`。
    挂起状态由 checkpoint 的 ``__interrupt__`` channel 持久化(多 worker
    部署天然兼容),不在进程内缓存。
    """
    for intr in interrupts:
        last_event_id += 1
        frame = _serialize_hitl_request(intr.value, interrupt_id=str(intr.id), event_id=last_event_id)
        await websocket.send_json(frame)
        first_action = frame["actions"][0] if frame["actions"] else {}
        logger.info(
            "WS confirmation_request 发送: session=%s, tool=%s, target=%s",
            session_id,
            first_action.get("tool_name", "?"),
            first_action.get("target_path", "?"),
        )
    return last_event_id
