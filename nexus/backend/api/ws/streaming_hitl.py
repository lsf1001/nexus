"""HITL 流式事件处理 — 从 streaming.py 拆出。

WHY 单独成包:streaming.py 累积到 881 行,超 §1.2 800 上限。HITL 三个 handler
逻辑独立(GraphInterrupt 兜底 + state.interrupts drain + confirmation 帧发出),
抽到独立模块,主模块聚焦 chunk / thinking / tool 事件分发。

被 streaming.py 的 :func:`_consume_astream_events` 调用,Handler 接收 ws + session
+ interrupts 元组,职责单一。

---

## 状态机抽象(:class:`HITLInterrupter`)

历史 3 个 module-level 函数只负责"发 confirmation_request 帧 + drain pending
interrupts",但**等待决策帧**(approve / edit / reject / respond)的逻辑散落在
``api/ws/handlers.py``,无法独立测超时 / 异常帧分支(2026-07 e2e timeout 0ms
误报 fail 的根因之一)。本模块把"等待决策"封为 :class:`HITLInterrupter` 类,
注入 ws 后 6 个分支可独立测试。

行为(``wait_decision``):

- action=approve  → Decision(action="approve")
- action=edit     → Decision(action="edit", content=frame["new_content"])
- action=respond  → Decision(action="respond", content=frame["response"])
- action=reject   → Decision(action="reject", reason=frame["reason"])
- 超时(``asyncio.TimeoutError``)→ Decision(action="reject", reason="timeout")
- 异常帧(type != "interrupt_decision")→ 发 protocol_error 帧 + Decision(reject, "protocol_error")
- 未知 action      → Decision(action="reject", reason=f"unknown action: {action!r}")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from .finalize import _serialize_hitl_request

__all__ = [
    "_emit_hitl_confirmation_frames",
    "_handle_graph_interrupt",
    "_drain_pending_hitl_interrupts",
    "Decision",
    "HITLInterrupter",
]


logger = logging.getLogger(__name__)


# === 状态机抽象 ===
#
# WHY frozen:Decision 是返回值,不希望下游误改 action / content(尤其 reject
# reason,可能进 audit log)。frozen=True 静态阻止 mutation。
@dataclass(frozen=True)
class Decision:
    """HITL 决策结果。``HITLInterrupter.wait_decision`` 唯一返回类型。

    Attributes:
        action: 决策类型,``"approve" | "edit" | "reject" | "respond"``。
            超时 / 异常帧走 ``"reject"`` 兜底。
        content: ``edit`` / ``respond`` 时承载用户修改后的内容;
            其他 action 留空字符串。
        reason: ``reject`` 时承载拒绝理由(用户给 / "timeout" /
            "protocol_error" / 未知 action);其他 action 留空字符串。
    """

    action: str
    content: str = ""
    reason: str = ""


class HITLInterrupter:
    """HITL 决策状态机:等 ws ``interrupt_decision`` 帧,直到收到合法 action 或超时。

    WHY 抽类:历史"等决策"逻辑散落在 :mod:`api.ws.handlers`,无注入点,
    无法独立验证 6 个分支(approve / edit / reject / respond / timeout /
    异常帧)。抽为类后注入 mock ws,6 个分支在
    :mod:`tests.test_streaming_hitl` 单元覆盖。

    线程模型:本类是纯 async 协程,不入子线程;WS 接收在事件循环中。
    调用方需要在已运行的 asyncio 事件循环中 ``await wait_decision(...)``。
    """

    def __init__(self, ws: Any, *, timeout: float = 300.0) -> None:
        """初始化 interrupter。

        Args:
            ws: 注入的 WebSocket-like 对象(``send_json`` / ``receive_json``
                两个 async 方法)。生产环境是 :class:`fastapi.WebSocket`;
                测试用 :class:`tests.test_streaming_hitl._StubWS` mock。
            timeout: 等待决策帧的最长秒数;超时走 reject 兜底。默认 300s
                覆盖典型人类决策时间,e2e 测试用 0.1-0.5s。
        """
        self._ws = ws
        self._timeout = timeout

    async def wait_decision(self, interrupt: Any) -> Decision:
        """等 ws ``interrupt_decision`` 帧,直到合法 action / 超时 / 异常帧。

        Args:
            interrupt: 触发 HITL 的 langgraph Interrupt 实例。
                本实现不读 ``interrupt.id`` / ``interrupt.value``(语义由
                调用方注入),仅作为未来审计 log 的标识占位。

        Returns:
            :class:`Decision` — 6 个分支之一:

            - 合法 ``interrupt_decision`` 帧 → 走 :meth:`_parse_decision`
              返回对应 action。
            - 超时 → ``Decision("reject", reason="timeout")``。
            - 异常帧(type != ``"interrupt_decision"``)→ 发 ``protocol_error``
              帧 + ``Decision("reject", reason="protocol_error")``。
        """
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    frame = await self._ws.receive_json()
                    if frame.get("type") != "interrupt_decision":
                        # 异常帧:发 protocol_error + 走 reject 兜底。
                        # WHY 不 raise:WS 流式循环不应被单帧异常中断,
                        # 兜底 reject 让 agent 走 abort-from-listen 路径
                        # 正常 finalize(用户可继续发下一轮)。
                        await self._ws.send_json(
                            {
                                "type": "protocol_error",
                                "reason": f"unexpected frame: {frame.get('type')!r}",
                            }
                        )
                        return Decision(action="reject", reason="protocol_error")
                    return self._parse_decision(frame)
        except TimeoutError:
            # WHY debug:超时是 e2e 偶发 flake 源,debug 级足够排查。
            logger.debug("HITL decision timeout (%.1fs), fallback to reject", self._timeout)
            return Decision(action="reject", reason="timeout")

    @staticmethod
    def _parse_decision(frame: dict[str, Any]) -> Decision:
        """把 ``interrupt_decision`` 帧翻译成 :class:`Decision`。

        Args:
            frame: WS 帧 dict,``type == "interrupt_decision"``,含 ``action``
                字段与对应 payload:

                - ``approve``: 无 payload
                - ``edit``: ``new_content``(用户改后的文本)
                - ``respond``: ``response``(用户回答)
                - ``reject``: ``reason``(拒绝理由)

        Returns:
            对应 action 的 :class:`Decision`。未知 action 走 reject 兜底
            (``reason=f"unknown action: {action!r}"``),不 raise — 跟异常帧
            兜底一致,WS 循环不应被单帧歧义中断。
        """
        action = frame.get("action")
        if action == "approve":
            return Decision(action="approve")
        if action == "edit":
            return Decision(action="edit", content=frame.get("new_content", ""))
        if action == "respond":
            return Decision(action="respond", content=frame.get("response", ""))
        if action == "reject":
            return Decision(action="reject", reason=frame.get("reason", ""))
        # 未知 action → reject 兜底(reason 标注具体 action 方便排查)
        return Decision(action="reject", reason=f"unknown action: {action!r}")


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
