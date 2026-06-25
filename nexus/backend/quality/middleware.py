"""质量门中间件：拦截写 AGENTS.md 的工具调用,做忠实度评估。

deepagents 0.6.8 的 :class:`MemoryMiddleware` 自动加载 ``AGENTS.md``
内容并注入 system prompt,LLM 用内置 ``edit_file`` / ``write_file``
自更新。本中间件在每次 ``edit_file`` / ``write_file`` 命中受保护路径
（即 ``~/.nexus/AGENTS.md`` 或项目级 ``AGENTS.md``）时,先用
:class:`MemoryFilter` 的 faithfulness rubric 评估新内容,通过则放行,
未通过则阻断并把原因回传 LLM 触发自我修正。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from .memory_filter import MemoryFilter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ContextT, ResponseT, ToolCallRequest
else:
    # runtime fallback: deepagents 实际不需要这些 TypeVar 在运行时被解析,
    # 但 AgentMiddleware[...] 在 PEP 695 之前的写法要求它们在运行时存在。
    from typing import Any as ContextT  # type: ignore[assignment,misc]
    from typing import Any as ResponseT  # type: ignore[assignment,misc]
    from typing import Any as ToolCallRequest  # type: ignore[assignment,misc]  # noqa: F811


logger = logging.getLogger(__name__)

# deepagents 内置文件工具名
_FILE_TOOLS: frozenset[str] = frozenset({"edit_file", "write_file"})

# 抽 user context 的窗口大小:最近 3 条 HumanMessage 拼成摘要,单条截断到
# 500 字,总长度上限 1500 字。足够 Judge 理解意图又不会撑爆 token。
_USER_CONTEXT_WINDOW: int = 3
_USER_CONTEXT_PER_MSG_CHARS: int = 500
_USER_CONTEXT_TOTAL_CHARS: int = 1500


class QualityGateMiddleware(AgentMiddleware[AgentState, ContextT, ResponseT]):
    """拦截对 AGENTS.md 的写入,用 MemoryFilter 做忠实度评估。

    Args:
        filter: 已构造的 :class:`MemoryFilter`,``check(value)`` 返回 :class:`FilterDecision`。
        protected_paths: 受保护路径字符串集合（绝对路径）;命中这些路径的工具调用会被评估。
    """

    state_schema = AgentState

    def __init__(
        self,
        *,
        filter: MemoryFilter,
        protected_paths: tuple[str, ...],
    ) -> None:
        if filter is None:
            raise ValueError("filter is required")
        if not protected_paths:
            raise ValueError("protected_paths must be non-empty")
        self._filter = filter
        # 用 set + str 化避免 Path vs str 比较踩坑
        self._protected = {str(Path(p).expanduser().resolve()) for p in protected_paths}

    def _extract_target_path(self, tool_call: dict[str, Any]) -> str | None:
        """从工具调用参数里抽出目标路径。deepagents 的 edit_file / write_file 用 'file_path' 或 'path'。"""
        args = tool_call.get("args", {})
        for key in ("file_path", "path", "target_path"):
            value = args.get(key)
            if value:
                return str(value)
        return None

    def _extract_content(self, tool_call: dict[str, Any]) -> str:
        """从工具调用参数里抽出要写入的内容。"""
        args = tool_call.get("args", {})
        # write_file 通常传 file_path + content
        for key in ("content", "new_content", "text"):
            value = args.get(key)
            if value:
                return str(value)
        # edit_file 通常传 old_string + new_string;取 new_string
        for key in ("new_string", "new_text", "replacement"):
            value = args.get(key)
            if value:
                return str(value)
        return ""

    def _is_protected(self, tool_call: dict[str, Any]) -> bool:
        tool_name = tool_call.get("name", "")
        if tool_name not in _FILE_TOOLS:
            return False
        target = self._extract_target_path(tool_call)
        if not target:
            return False
        try:
            resolved = str(Path(target).expanduser().resolve())
        except (OSError, RuntimeError) as exc:
            logger.debug("路径解析失败 %s: %s", target, exc)
            return False
        return resolved in self._protected

    def _extract_user_context(self, state: Any) -> str | None:
        """从 agent state 抽最近 N 条 HumanMessage 拼成 user context。

        WHY: :meth:`MemoryFilter.check` 的 Judge LLM 拿不到对话历史,只看到
        要写入的字符串,faithfulness 维度会把"用户明确要求写入的具体值"
        误判为"完全没回答问题" → 0.0 分 → 工具被拒 → WS 流提前结束。
        注入最近 user 消息后,Judge 能区分"用户要写的标记串"vs
        "凭空捏造的乱写"。

        Args:
            state: deepagents 的 AgentState,期望含 ``messages`` 键。

        Returns:
            拼接好的中文 user context,或 ``None``(取不到时让 filter 退回
            旧版兼容路径)。
        """
        if not isinstance(state, dict):
            return None
        messages = state.get("messages")
        if not messages:
            return None
        humans = [m for m in messages if isinstance(m, HumanMessage)]
        if not humans:
            return None
        recent = humans[-_USER_CONTEXT_WINDOW:]
        parts: list[str] = []
        for idx, msg in enumerate(recent, start=1):
            content = getattr(msg, "content", "") or ""
            content = str(content).strip()
            if not content:
                continue
            if len(content) > _USER_CONTEXT_PER_MSG_CHARS:
                content = content[:_USER_CONTEXT_PER_MSG_CHARS] + "...(已截断)"
            parts.append(f"[{idx}] {content}")
        joined = "\n".join(parts)
        if len(joined) > _USER_CONTEXT_TOTAL_CHARS:
            joined = joined[:_USER_CONTEXT_TOTAL_CHARS] + "...(已截断)"
        return joined or None

    def _make_reject_message(self, tool_call: dict[str, Any], reason: str) -> ToolMessage:
        return ToolMessage(
            content=f"[质量门阻断] {reason}",
            tool_call_id=tool_call.get("id", ""),
            name=tool_call.get("name", ""),
            status="error",
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """异步版本：拦截 edit_file/write_file 对 AGENTS.md 的写入。"""
        tool_call = request.tool_call
        if not self._is_protected(tool_call):
            return await handler(request)

        content = self._extract_content(tool_call)
        if not content:
            # 没有内容可评估,放行
            return await handler(request)

        user_context = self._extract_user_context(request.state)
        decision = await self._filter.check(content, user_context=user_context)
        if not decision.allow:
            logger.warning(
                "质量门阻断 %s: score=%.2f reason=%s",
                tool_call.get("name"),
                decision.score,
                decision.reason,
            )
            return self._make_reject_message(tool_call, decision.reason)

        logger.debug(
            "质量门放行 %s: score=%.2f has_user_context=%s",
            tool_call.get("name"),
            decision.score,
            user_context is not None,
        )
        return await handler(request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """同步版本: 通过 asyncio.run 跑异步实现。"""
        import asyncio

        async def _run() -> ToolMessage | Command[Any]:
            return await self.awrap_tool_call(request, lambda r: _sync(handler, r))

        return asyncio.run(_run())


async def _sync(
    handler: Callable[[Any], Any],
    request: Any,
) -> Any:
    """桥接 sync handler 到 async（让 wrap_tool_call 也能用 sync handler)。"""
    return handler(request)


__all__ = ["QualityGateMiddleware"]
