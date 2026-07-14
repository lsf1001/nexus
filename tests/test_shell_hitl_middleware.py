"""``nexus.backend.middleware.shell.ShellHITLMiddleware`` 单元测试。

覆盖三类路径:
  1. **正常**:非 ``shell_run`` 透传;合法 ``shell_run`` 调 ``interrupt()``,
     approve → handler 跑通,reject → deny。
  2. **边界**:危险命令短路(不弹 HITL);cwd 越界短路;HITL payload 字段完整。
  3. **异常**:``interrupt`` 返回空 decisions;reject reason 注入 deny message;
     异步路径 ``awrap_tool_call`` 同样语义。

WHY 必须 mock ``interrupt``:
  ``interrupt()`` 是 langgraph Pregel loop 注入的"挂起点",单元测试里没
  有 Pregel 上下文 —— 必须用 ``monkeypatch.setattr`` 把
  ``nexus.backend.middleware.shell.interrupt`` 替换成可控的 fake,
  让它返回 simulate 的 "用户决策"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from nexus.backend.middleware.shell import (
    _SHELL_TOOL_NAME,
    ShellHITLMiddleware,
)


def _make_request(*, tool_name: str, args: dict[str, Any] | None = None, call_id: str = "tc-1") -> Any:
    """构造 wrap_tool_call / awrap_tool_call 的 request。

    ``request.tool_call`` 是一个 dict(name / args / id) —— langgraph
    ToolCallRequest 的实际形态(参见 PathAwareHITLMiddleware 测试)。
    """
    return type(
        "FakeRequest",
        (),
        {"tool_call": {"name": tool_name, "args": args or {}, "id": call_id}},
    )()


def _make_handler(return_value: ToolMessage | None = None) -> Any:
    """构造"如果放行就调这个"的 handler。

    默认返回值是一个简单的 ToolMessage,表示"工具跑成功了"。
    """
    captured: list[Any] = []

    def handler(req: Any) -> ToolMessage:
        captured.append(req)
        return return_value or ToolMessage(
            content="handler-ran",
            tool_call_id=req.tool_call.get("id", ""),
            name=req.tool_call.get("name", ""),
        )

    handler.captured = captured  # type: ignore[attr-defined]
    return handler


# === 非 shell_run 透传 ===


def test_non_shell_tool_passes_through() -> None:
    """非 ``shell_run`` 工具 → middleware 不拦截,handler 立刻被调。"""
    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(tool_name="read_file", args={"path": "/tmp/x"})

    result = mw.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "handler-ran"
    assert len(handler.captured) == 1  # type: ignore[attr-defined]


# === 危险命令短路(不弹 HITL)===


@pytest.mark.parametrize(
    "dangerous",
    ["rm -rf /", "sudo apt install x", "shutdown -h now", ":(){ :|:& };:"],
)
def test_dangerous_command_denied_without_interrupt(dangerous: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """危险命令 → 直接 deny ToolMessage,**不**调 ``interrupt``(不应弹 HITL)。

    验证方式:``interrupt`` 被调一次则失败。
    """
    interrupt_calls: list[Any] = []

    def fake_interrupt(payload: Any) -> Any:
        interrupt_calls.append(payload)
        return {"decisions": [{"type": "approve"}]}

    import nexus.backend.middleware.shell as mw_mod

    monkeypatch.setattr(mw_mod, "interrupt", fake_interrupt)

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": dangerous, "cwd": str(path_home_nexus())},
    )
    result = mw.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert "[Shell 沙箱阻断]" in result.content
    assert result.status == "error"
    assert interrupt_calls == [], f"危险命令不应触发 interrupt,但调用了 {interrupt_calls}"
    assert handler.captured == []  # type: ignore[attr-defined] # handler 未被调用


def path_home_nexus() -> Any:
    """小工具函数:返回 ``~/.nexus/outputs`` 路径(沙箱白名单子目录)。"""
    from pathlib import Path

    return Path.home() / ".nexus" / "outputs"


# === cwd 越界短路 ===


@pytest.mark.parametrize(
    "bad_cwd",
    [None, "", "/tmp", "/Users/yxb/Documents", "/etc/passwd"],
)
def test_cwd_outside_whitelist_denied_without_interrupt(bad_cwd: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """cwd 越界 → 直接 deny,不弹 HITL。"""
    interrupt_calls: list[Any] = []
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: interrupt_calls.append(payload) or {"decisions": [{"type": "approve"}]},
    )

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls", "cwd": bad_cwd},
    )
    result = mw.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert "[Shell 沙箱阻断]" in result.content
    assert interrupt_calls == []


# === 合法命令弹 HITL ===


def test_legitimate_command_triggers_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合法 ``shell_run`` 调用应触发 ``interrupt``,payload 含完整字段。"""
    received_payload: list[Any] = []

    def fake_interrupt(payload: Any) -> Any:
        received_payload.append(payload)
        return {"decisions": [{"type": "approve"}]}

    monkeypatch.setattr("nexus.backend.middleware.shell.interrupt", fake_interrupt)

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    nexus_cwd = str(path_home_nexus() / "outputs")
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls -la", "cwd": nexus_cwd, "timeout": 60},
    )
    result = mw.wrap_tool_call(request, handler)

    assert isinstance(received_payload, list)
    assert len(received_payload) == 1
    payload = received_payload[0]

    # 校验 payload 结构
    assert "action_requests" in payload
    assert "review_configs" in payload
    action_req = payload["action_requests"][0]
    assert action_req["name"] == _SHELL_TOOL_NAME
    assert action_req["args"]["command"] == "ls -la"
    assert action_req["args"]["cwd"] == nexus_cwd
    assert "description" in action_req
    assert "ls -la" in action_req["description"]
    assert nexus_cwd in action_req["description"]

    review = payload["review_configs"][0]
    assert review["action_name"] == _SHELL_TOOL_NAME
    assert "approve" in review["allowed_decisions"]
    assert "reject" in review["allowed_decisions"]

    # approve → handler 被调用
    assert isinstance(result, ToolMessage)
    assert result.content == "handler-ran"


def test_interrupt_reject_returns_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """HITL 用户 reject → 返回 deny ToolMessage,handler 不被调。"""
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: {"decisions": [{"type": "reject", "message": "我拒绝"}]},
    )

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls", "cwd": str(path_home_nexus())},
    )
    result = mw.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert "[HITL 拒绝]" in result.content
    assert "我拒绝" in result.content
    assert handler.captured == []  # type: ignore[attr-defined]


def test_interrupt_empty_decisions_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """HITL 返回空 decisions 列表 → deny(防 Pregel 异常 race)。"""
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: {"decisions": []},
    )

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls", "cwd": str(path_home_nexus())},
    )
    result = mw.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert "[Shell 沙箱阻断]" in result.content
    assert "用户决策列表为空" in result.content


def test_interrupt_reject_without_message_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reject 但没传 message → 用默认 reason。"""
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: {"decisions": [{"type": "reject"}]},
    )

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls", "cwd": str(path_home_nexus())},
    )
    result = mw.wrap_tool_call(request, handler)

    assert "[HITL 拒绝]" in result.content
    assert "用户拒绝执行 shell 命令" in result.content


# === 异步路径(awrap_tool_call)===


@pytest.mark.asyncio
async def test_awrap_dangerous_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """异步入口的危险命令短路语义与同步一致。"""
    interrupt_calls: list[Any] = []
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: interrupt_calls.append(payload) or {"decisions": [{"type": "approve"}]},
    )

    mw = ShellHITLMiddleware()

    async def fake_handler(req: Any) -> ToolMessage:
        return ToolMessage(content="should-not-run", tool_call_id=req.tool_call["id"], name="shell_run")

    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "rm -rf /", "cwd": str(path_home_nexus())},
    )
    result = await mw.awrap_tool_call(request, fake_handler)

    assert isinstance(result, ToolMessage)
    assert "[Shell 沙箱阻断]" in result.content
    assert interrupt_calls == []


@pytest.mark.asyncio
async def test_awrap_approve_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """异步 approve → handler 跑通。"""
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: {"decisions": [{"type": "approve"}]},
    )

    mw = ShellHITLMiddleware()

    async def fake_handler(req: Any) -> ToolMessage:
        return ToolMessage(
            content="async-handler-ran",
            tool_call_id=req.tool_call["id"],
            name=req.tool_call["name"],
        )

    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls", "cwd": str(path_home_nexus())},
    )
    result = await mw.awrap_tool_call(request, fake_handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "async-handler-ran"


@pytest.mark.asyncio
async def test_awrap_reject_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """异步 reject → deny。"""
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: {"decisions": [{"type": "reject", "message": "no"}]},
    )

    mw = ShellHITLMiddleware()

    async def fake_handler(req: Any) -> ToolMessage:
        raise AssertionError("handler 不应被调")

    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "ls", "cwd": str(path_home_nexus())},
    )
    result = await mw.awrap_tool_call(request, fake_handler)

    assert "[HITL 拒绝]" in result.content
    assert "no" in result.content


# === 中间件 deny 写审计(2026-07-14 E2E 发现中间件短路漏 audit)===


def test_dangerous_deny_writes_audit_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """危险命令被中间件拦截 → 审计 ``decision=auto_deny`` 写入。

    WHY:之前中间件 deny 只返回 ToolMessage,不写审计 → 用户事后查
    ``~/.nexus/logs/shell_executions.log`` 看不到"LLM 试图跑过 rm -rf"。
    """
    import nexus.backend.shell_audit as audit_mod

    log_dir = tmp_path / "logs"
    log_file = log_dir / "shell_executions.log"
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_DIR", log_dir)
    monkeypatch.setattr(audit_mod, "AUDIT_LOG_FILE", log_file)

    interrupt_calls: list[Any] = []
    monkeypatch.setattr(
        "nexus.backend.middleware.shell.interrupt",
        lambda payload: interrupt_calls.append(payload) or {"decisions": [{"type": "approve"}]},
    )

    mw = ShellHITLMiddleware()
    handler = _make_handler()
    request = _make_request(
        tool_name=_SHELL_TOOL_NAME,
        args={"command": "rm -rf /", "cwd": str(path_home_nexus())},
    )
    result = mw.wrap_tool_call(request, handler)

    assert "[Shell 沙箱阻断]" in result.content
    assert interrupt_calls == [], "危险命令不应触发 HITL"
    assert log_file.exists(), "中间件 deny 必须写审计"
    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["decision"] == "auto_deny"
    assert record["exit_code"] is None
    assert record["risk_label"] == "recursive_force_delete"
    assert "rm -rf" in record["command"]
