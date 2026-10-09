"""HITLInterrupter 单元测试。

WHY: 历史 HITL 状态机以 module-level 函数形式存在,不可注入 ws,不可
独立测超时 / approve / reject 分支。抽为 ``HITLInterrupter`` 类后,本
测试用 mock ws 验证 6 个分支。

测试矩阵(6 个分支):

- ``approve``   → Decision(action="approve")
- ``edit``      → Decision(action="edit", content=<new_content>)
- ``respond``   → Decision(action="respond", content=<response>)
- ``reject``    → Decision(action="reject", reason=<reason>)
- 超时          → Decision(action="reject", reason="timeout")
- 异常帧        → 发 protocol_error 帧 + Decision(action="reject", reason="protocol_error")
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


class _StubWS:
    """最小可用 WebSocket mock,只记录 send / receive 的内容。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def receive_json(self) -> dict[str, Any]:
        # 无 frame 排队时 sleep 一个超过外层 timeout 的时长,让 ``asyncio.timeout``
        # 先触发;否则默认返回 ping 会被实现判定为"异常帧"走 protocol_error 分支,
        # timeout 测试永远进不到 TimeoutError 分支。
        if not self.received:
            await asyncio.sleep(60.0)
            return {"type": "ping"}
        return self.received.pop(0)


def _mock_interrupt() -> Any:
    """Mock 一个带 id + value 的 langgraph Interrupt,适配 GraphInterrupt 路径。

    现有 ``streaming_hitl.py`` 的 :func:`_handle_graph_interrupt` 从
    ``gi.args[0]`` 拿 interrupts 序列,每个 interrupt 需有 ``id`` 与 ``value``。
    本测试不调用该函数,只把 mock interrupt 传给 ``HITLInterrupter.wait_decision``,
    所以 interrupt 实际只用于标注身份,只要传得进去即可。
    """
    from langgraph.types import Interrupt

    return Interrupt(value={"question": "approve?"}, id="i1")


async def _run(interrupter: Any, interrupt: Any) -> Any:
    """Helper: 跑 wait_decision 直到完成。"""
    return await interrupter.wait_decision(interrupt)


@pytest.fixture
def interrupter() -> Any:
    """默认 fixture: 给 ``_StubWS`` + 0.5s 超时。"""
    from nexus.backend.api.ws.streaming_hitl import HITLInterrupter

    return HITLInterrupter(ws=_StubWS(), timeout=0.5)


# --- 6 个分支测试 ---


async def test_approve_decision_returns_approved(interrupter: Any) -> None:
    """收到 approve 帧 → 返回 Decision(action='approve')。"""
    interrupter._ws.received = [{"type": "interrupt_decision", "action": "approve"}]  # type: ignore[attr-defined]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "approve"


async def test_reject_decision_returns_rejected(interrupter: Any) -> None:
    """收到 reject 帧 → 返回 Decision(action='reject', reason=<reason>)。"""
    interrupter._ws.received = [{"type": "interrupt_decision", "action": "reject", "reason": "no"}]  # type: ignore[attr-defined]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "reject"
    assert decision.reason == "no"


async def test_edit_decision_returns_modified_content(interrupter: Any) -> None:
    """收到 edit 帧 → 返回 Decision(action='edit', content=<new_content>)。"""
    interrupter._ws.received = [  # type: ignore[attr-defined]
        {
            "type": "interrupt_decision",
            "action": "edit",
            "new_content": "user edited text",
        }
    ]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "edit"
    assert decision.content == "user edited text"


async def test_respond_decision_returns_user_response(interrupter: Any) -> None:
    """收到 respond 帧 → 返回 Decision(action='respond', content=<response>)。"""
    interrupter._ws.received = [  # type: ignore[attr-defined]
        {
            "type": "interrupt_decision",
            "action": "respond",
            "response": "answer from user",
        }
    ]
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "respond"
    assert decision.content == "answer from user"


async def test_timeout_falls_back_to_reject() -> None:
    """无 decision 帧 + 超时 → 走 reject 兜底,reason='timeout'。"""
    from nexus.backend.api.ws.streaming_hitl import HITLInterrupter

    ws = _StubWS()
    # ws.received = [] → _StubWS.receive_json 默认返回 ping → 永远拿不到 interrupt_decision
    interrupter = HITLInterrupter(ws=ws, timeout=0.1)
    decision = await _run(interrupter, _mock_interrupt())
    assert decision.action == "reject"
    assert decision.reason == "timeout"


async def test_protocol_error_sends_error_frame() -> None:
    """收到异常帧(非 interrupt_decision 类型)→ 发 protocol_error 帧 + reject。

    注: ping 帧也算异常帧(因为 type != interrupt_decision)—— 收到 ping
    即触发 protocol_error 分支,这是设计选择(实现要求严格校验帧类型,
    见 wait_decision 的 type 校验)。
    """
    from nexus.backend.api.ws.streaming_hitl import HITLInterrupter

    ws = _StubWS()
    # 发送一帧 type 未知 → 立刻触发 protocol_error
    ws.received = [{"type": "unknown_frame"}]
    interrupter = HITLInterrupter(ws=ws, timeout=0.5)
    decision = await _run(interrupter, _mock_interrupt())
    # 收到异常帧 → 应发 protocol_error 帧 + 走 reject
    assert any(f.get("type") == "protocol_error" for f in ws.sent)
    assert decision.action == "reject"
    assert decision.reason == "protocol_error"
