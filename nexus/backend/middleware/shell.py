"""Shell 工具的 HITL 中间件:对 ``shell_run`` 工具强制走人类审批。

WHY 独立模块(2026-07-14)
------------------------
``PathAwareHITLMiddleware`` 是按"路径"判定 HITL;``ShellHITLMiddleware``
是按"命令字符串 + cwd"判定。两套判定逻辑不通用(命令危险模式 ≠ 路径危险
前缀),所以独立成模块,不复用 ``PathAwareHITLMiddleware``。

WHY 不在工具内部调 ``interrupt()``
---------------------------------
``langgraph.types.interrupt()`` 只能在 langgraph 节点执行上下文(由 Pregel
loop 调度)里工作 —— 抛 ``GraphInterrupt`` 由 ``_run_agent_streaming`` 捕获
后翻译成 ``confirmation_request`` 帧。**普通 ``@langchain_tool`` 装饰函数
里调 ``interrupt()`` 不会抛**(没有 Pregel 上下文,只能返回 sentinel)。
所以 HITL 必须由 ``AgentMiddleware.wrap_tool_call`` 在 deepagents 主循环
里抛,这与 ``PathAwareHITLMiddleware`` 同款。

WHY 三态分流
------------
  1. **危险命令**(rm -rf / / sudo / fork bomb 等)→ 直接 deny,返回
     ``ToolMessage(status="error")``,**不弹 HITL** —— 用户不该看到这种
     命令的卡片,LLM 应自主改写。
  2. **cwd 越界**(``~/Documents/x`` / ``/tmp/x`` 等)→ 直接 deny,同上。
  3. **其它**(白名单内 + 非危险命令)→ 弹 HITL 让用户决策。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

from ..shell_audit import append_log as _audit_append
from ..shell_sandbox import (
    classify_dangerous_command,
    validate_command,
    validate_cwd,
    validate_timeout,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ContextT, ResponseT, ToolCallRequest
else:
    # runtime fallback: 同 nexus.backend.middleware.hitl 的写法
    from typing import Any as ContextT  # type: ignore[assignment,misc]
    from typing import Any as ResponseT  # type: ignore[assignment,misc]
    from typing import Any as ToolCallRequest  # type: ignore[assignment,misc]  # noqa: F811

logger = logging.getLogger(__name__)

_SHELL_TOOL_NAME = "shell_run"


def _extract_shell_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    """抽出 ``shell_run`` 入参 ``command`` / ``cwd`` / ``timeout``。

    Args 是 dict 但 LLM 可能漏传或传 None,全部用 ``or`` 兜底成空字符串 /
    ``None``,让下游 ``shell_sandbox`` 走"空值拒绝"分支。
    """
    args = tool_call.get("args", {}) or {}
    return {
        "command": args.get("command") or "",
        "cwd": args.get("cwd"),
        "timeout": args.get("timeout"),
    }


class ShellHITLMiddleware(AgentMiddleware[Any, ContextT, ResponseT]):
    """``shell_run`` 工具的 HITL 守卫中间件。

    判定顺序(短路):
      1. 不是 ``shell_run`` → 透传 handler(本中间件不关心其它工具)。
      2. ``validate_command`` 失败 → 直接 deny,LLM 改写。
      3. ``validate_cwd`` 失败 → 直接 deny,LLM 改写。
      4. 其它 → ``interrupt()`` 弹 HITL,等用户决策。

    Args:
        无显式参数;沙箱规则(白名单 / 黑名单 / 超时上限)在
        :mod:`nexus.backend.shell_sandbox` 里集中维护,本中间件只负责
        拦截 + 翻译 payload,不改规则。
    """

    def _make_deny_message(self, tool_call: dict[str, Any], reason: str) -> ToolMessage:
        """沙箱 deny(不弹 HITL,直接返回 error ToolMessage)。"""
        return ToolMessage(
            content=f"[Shell 沙箱阻断] {reason}",
            tool_call_id=tool_call.get("id", ""),
            name=_SHELL_TOOL_NAME,
            status="error",
        )

    def _audit_deny(self, tool_call: dict[str, Any], reason: str, risk_label: str | None) -> None:
        """中间件级 deny 写审计(让安全审计反映完整拦截链)。

        WHY 在中间件也写:
          危险命令被中间件拦截 → ``shell_run`` 工具函数**未被 invoke** → 工具
          入口的审计不写 → 用户事后查日志看不到"曾试图跑 rm -rf"。这里兜底
          一行 ``decision=auto_deny``,exit_code=None。
        """
        shell_args = _extract_shell_args(tool_call)
        try:
            _audit_append(
                command=shell_args["command"],
                cwd=shell_args["cwd"] or "(未指定)",
                exit_code=None,
                stdout_snippet="",
                stderr_snippet=f"沙箱拒绝: {reason}",
                user_decision="auto_deny",
                risk_label=risk_label,
            )
        except Exception as audit_exc:  # noqa: BLE001
            logger.warning("ShellHITL audit_deny 失败: %s", audit_exc)

    def _build_hitl_request(self, tool_call: dict[str, Any], *, risk_label: str | None) -> dict[str, Any]:
        """构造 langchain HITL 标准 payload,供 ``interrupt()`` 抛。

        ``action_requests[0].args`` 字段含 ``command`` / ``cwd`` /
        ``timeout`` —— 这是前端 ConfirmationCard 渲染命令块 + cwd + 超时
        提示的直接数据源(后续可增强渲染)。

        ``description`` 字段给一个"为什么弹窗"的人类可读解释,前端
        fallback 渲染它。
        """
        shell_args = _extract_shell_args(tool_call)
        command = shell_args["command"]
        cwd = shell_args["cwd"] or "(未指定)"
        timeout = validate_timeout(shell_args["timeout"])
        risk_part = f"\n风险标签: {risk_label}" if risk_label else ""

        description = (
            f"LLM 申请执行 shell 命令,需要你确认\n"
            f"工具: {_SHELL_TOOL_NAME}\n"
            f"命令: {command}\n"
            f"工作目录: {cwd}\n"
            f"超时: {timeout}s{risk_part}"
        )

        action_request = {
            "name": _SHELL_TOOL_NAME,
            # args 字段复用 LLM 入参(WS _serialize_hitl_request 会读它)
            "args": dict(tool_call.get("args", {}) or {}),
            "description": description,
        }
        review_config = {
            "action_name": _SHELL_TOOL_NAME,
            "allowed_decisions": ["approve", "reject"],
        }
        return {
            "action_requests": [action_request],
            "review_configs": [review_config],
        }

    def _should_deny(self, tool_call: dict[str, Any]) -> bool:
        """判定这次调用是否应该直接 deny(危险命令 OR cwd 越界)。"""
        if tool_call.get("name") != _SHELL_TOOL_NAME:
            return False
        shell_args = _extract_shell_args(tool_call)
        ok_cmd, cmd_reason = validate_command(shell_args["command"])
        if not ok_cmd:
            return True
        ok_cwd, _cwd_resolved = validate_cwd(shell_args["cwd"])
        if not ok_cwd:
            return True
        return False

    def _deny_reason(self, tool_call: dict[str, Any]) -> tuple[str, str | None]:
        """返回 ``(reason, risk_label)`` 给 ``_make_deny_message`` 用。

        ``risk_label`` 在 ``validate_command`` 命中时 = 模式 label,其它
        (cwd 越界 / 空命令) = ``None``。
        """
        shell_args = _extract_shell_args(tool_call)
        ok_cmd, cmd_reason = validate_command(shell_args["command"])
        if not ok_cmd:
            risk_label = classify_dangerous_command(shell_args["command"])
            return cmd_reason, risk_label
        ok_cwd, cwd_reason = validate_cwd(shell_args["cwd"])
        if not ok_cwd:
            return cwd_reason, None
        return "未知原因(请检查 shell_run 入参)", None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """同步入口:非 ``shell_run`` 透传;危险 deny;其它 HITL。

        三态分流顺序敏感:
          1. 非 ``shell_run`` → handler(request) 直接放行
          2. ``_should_deny`` → 直接返回 deny ToolMessage
          3. 其它 → ``interrupt(hitl_request)``,用户 approve / reject
        """
        tool_call = request.tool_call
        if tool_call.get("name") != _SHELL_TOOL_NAME:
            return handler(request)
        if self._should_deny(tool_call):
            reason, risk_label = self._deny_reason(tool_call)
            logger.warning(
                "ShellHITL deny: command=%s cwd=%s reason=%s risk=%s",
                _extract_shell_args(tool_call)["command"][:100],
                _extract_shell_args(tool_call)["cwd"],
                reason,
                risk_label,
            )
            self._audit_deny(tool_call, reason, risk_label)
            return self._make_deny_message(tool_call, reason)

        hitl_request = self._build_hitl_request(tool_call, risk_label=None)
        logger.info(
            "ShellHITL interrupt: command=%s cwd=%s",
            _extract_shell_args(tool_call)["command"][:100],
            _extract_shell_args(tool_call)["cwd"],
        )
        decisions: list[dict[str, Any]] = interrupt(hitl_request)["decisions"]  # type: ignore[index]
        if not decisions:
            return self._make_deny_message(tool_call, "用户决策列表为空")
        decision = decisions[0]
        if decision.get("type") == "approve":
            return handler(request)
        # reject / edit / respond 一律视为拒绝
        reason = decision.get("message") or "用户拒绝执行 shell 命令"
        return self._make_deny_message(tool_call, f"[HITL 拒绝] {reason}")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """异步入口:与同步版语义一致,deepagents 0.5.x 主路径走这里。"""
        tool_call = request.tool_call
        if tool_call.get("name") != _SHELL_TOOL_NAME:
            return await handler(request)
        if self._should_deny(tool_call):
            reason, risk_label = self._deny_reason(tool_call)
            logger.warning(
                "ShellHITL async deny: command=%s cwd=%s reason=%s risk=%s",
                _extract_shell_args(tool_call)["command"][:100],
                _extract_shell_args(tool_call)["cwd"],
                reason,
                risk_label,
            )
            self._audit_deny(tool_call, reason, risk_label)
            return self._make_deny_message(tool_call, reason)

        hitl_request = self._build_hitl_request(tool_call, risk_label=None)
        decisions: list[dict[str, Any]] = interrupt(hitl_request)["decisions"]  # type: ignore[index]
        if not decisions:
            return self._make_deny_message(tool_call, "用户决策列表为空")
        decision = decisions[0]
        if decision.get("type") == "approve":
            return await handler(request)
        reason = decision.get("message") or "用户拒绝执行 shell 命令"
        return self._make_deny_message(tool_call, f"[HITL 拒绝] {reason}")


__all__ = ["ShellHITLMiddleware"]
