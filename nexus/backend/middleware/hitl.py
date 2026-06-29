"""路径感知的 HITL 中间件:对"非白名单"的写操作触发人类确认。

WHY 存在
--------
deepagents 0.5.3 的 ``FilesystemPermission.mode`` 只支持
``Literal["allow", "deny"]``(**没有** ``"interrupt"`` mode);HITL 必须通过
``HumanInTheLoopMiddleware`` + ``interrupt_on`` 参数注册,而 Nexus 历史上
既没传 ``interrupt_on``,又把 ``mode="interrupt"`` 当作"白名单之外都触发 HITL"
的开关写在 :mod:`nexus.backend.permissions`,实际被 deepagents 0.5.3 静默
忽略,落到 permissive default allow。结果是 LLM 写项目源码 / 写 ``/tmp``
都不会弹窗,直接落到磁盘 — E2E 2026-06-29 ``test_e2e_interrupt_source``
等 5 个场景全部 FAIL,根因与 refactor 无关(pre-existing)。

本中间件在 ``wrap_tool_call`` 阶段:
  1. 判定工具是不是写工具(``write_file`` / ``edit_file`` 等)
  2. 提取目标路径,解析成绝对路径
  3. 路径在白名单(``{project_root}/.nexus/**``)→ 直接放行,无 HITL
  4. 路径不在白名单 → 调 :func:`langgraph.types.interrupt` 抛 ``GraphInterrupt``,
     payload 是 langchain HITL 标准格式 ``{"action_requests": [...], ...}``
     — :func:`nexus.backend.api.ws.finalize._serialize_hitl_request` 不用改
     就能消费。

为什么不用 ``HumanInTheLoopMiddleware`` 直接传 ``interrupt_on``
----------------------------------------------------------------
``HumanInTheLoopMiddleware.after_model`` 是**按工具名**判定是否触发,
不支持 per-call ``when`` 谓词。如果 ``interrupt_on={"write_file": True}``,
所有 ``write_file`` 都弹窗(包括 ``.nexus/outputs/`` 这种纯产物路径)—
体验差。本中间件做路径白名单:只有"非白名单"路径才弹窗,与产品质量预期对齐。

与 :class:`QualityGateMiddleware` 的分工
----------------------------------------
- ``QualityGateMiddleware``:拦截 :file:`~/.nexus/AGENTS.md` 的写入,
  跑 ``MemoryFilter`` faithfulness 评估(机器判断)。
- 本中间件:拦截其它非白名单写入,弹窗给用户决策(人类判断)。
- 顺序:QualityGate 先(它只关心 AGENTS.md,路径白名单外的危险路径会被
  本中间件拦下,QualityGate 不会重复处理)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

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


# deepagents 暴露给 LLM 的写文件工具名集合(与 QualityGateMiddleware 同步)。
_FILE_TOOLS: frozenset[str] = frozenset(
    {
        "edit_file",
        "write_file",
        "create_file",
        "apply_patch",
        "patch_file",
        "str_replace_editor",
        "write_document",
    }
)

# 黑名单兜底模式:工具名包含这些子串即视为写文件工具。
_WRITE_TOOL_PATTERNS: tuple[str, ...] = (
    "write_",
    "edit_",
    "patch_",
    "apply_",
    "_file",
    "_document",
)

# 明确只读工具白名单 — 即使名称含 file/document 也不视为写。
_READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "ls",
        "glob",
        "grep",
        "internet_search",
    }
)


def _is_write_tool(tool_name: str) -> bool:
    """判断工具名是否对应文件写操作(可能触发 HITL)。"""
    if not tool_name:
        return False
    if tool_name in _FILE_TOOLS:
        return True
    name = tool_name.lower()
    if name in _READ_ONLY_TOOLS:
        return False
    return any(pattern in name for pattern in _WRITE_TOOL_PATTERNS)


def _extract_target_path(args: dict[str, Any]) -> str | None:
    """从工具调用入参里抽出目标路径。

    deepagents 的 ``edit_file`` / ``write_file`` 用 ``file_path``;部分别名
    用 ``path`` / ``target_path``。这里三个都识别,取第一个非空值。
    """
    for key in ("file_path", "path", "target_path"):
        value = args.get(key)
        if value:
            return str(value)
    return None


def _extract_content(args: dict[str, Any]) -> str:
    """从工具调用入参里抽出要写入的内容(用于弹窗预览)。"""
    for key in ("content", "new_content", "text"):
        value = args.get(key)
        if value:
            return str(value)
    for key in ("new_string", "new_text", "replacement"):
        value = args.get(key)
        if value:
            return str(value)
    return ""


class PathAwareHITLMiddleware(AgentMiddleware[Any, ContextT, ResponseT]):
    """路径感知的 HITL 中间件:对非白名单写入抛 ``GraphInterrupt``。

    Args:
        project_root: 项目根目录;白名单 = ``{project_root}/.nexus/**``。
        protected_paths: 由 :func:`nexus.backend.permissions.resolve_protected_paths`
            解析出来的 AGENTS.md 绝对路径集合;这些路径**不**被本中间件拦截,
            由 :class:`QualityGateMiddleware` 负责(避免双重弹窗)。
        description_prefix: 弹窗 description 前缀,默认写"工具名 + 目标路径"。

    Note:
        路径分流(三态):
          1. **白名单**(项目级 ``{project_root}/.nexus/**`` + 用户级
             ``~/.nexus/outputs|state|logs|skills|cache/**``)→ 直接 allow,
             无 HITL。
          2. **危险路径**(``/tmp`` / ``/etc`` / ``/var`` / ``/usr`` /
             ``/bin`` / ``/sbin`` / ``/System`` / ``/private/etc`` 等
             系统级目录)→ 直接 deny,返回 ``ToolMessage(status="error")``,
             LLM 看到"permission denied",**不弹 HITL**(系统级不该让用户决策)。
          3. **其它非白名单路径**(典型:项目源码 ``nexus/backend/foo.py``、
             用户家目录其它子目录)→ 触发 HITL,让用户在前端弹窗决策。
    """

    # 用户级 ~/.nexus/ 下的白名单子目录(Nexus 是 OpenClaw 个人助理,
    # 这些目录是 LLM 的"产出物 / 配置 / 状态 / 日志 / 技能"归宿)。
    _USER_WHITELIST_SUBDIRS: tuple[str, ...] = (
        "outputs",
        "state",
        "logs",
        "skills",
        "cache",
    )

    # 系统级危险路径前缀(deny,不弹 HITL)。
    #
    # macOS symlink 漂移: ``/tmp`` → ``/private/tmp``、``/etc`` → ``/private/etc``。
    # ``Path.resolve()`` 把这些符号链接展开成 ``/private/...``,所以前缀
    # 要把 ``/tmp/`` 和 ``/private/tmp/`` 都列出来。
    #
    # **不列** ``/var/`` / ``/private/var/`` / 泛 ``/private/``:
    # ``tempfile.TemporaryDirectory()`` 在 macOS 上落在
    # ``/var/folders/jr/.../T/...``,resolve 后变成 ``/private/var/folders/...`` —
    # 这是用户临时目录,**合法**(pytest 大量测试用)。只列 ``/var/`` 泛前缀
    # 会把它们误归为危险,导致所有基于 tempfile 的测试 FAIL。
    _DANGEROUS_PREFIXES: tuple[str, ...] = (
        "/tmp/",
        "/private/tmp/",
        "/etc/",
        "/private/etc/",
        "/usr/",
        "/bin/",
        "/sbin/",
        "/System/",
        "/Library/",
    )

    def __init__(
        self,
        *,
        project_root: Path,
        protected_paths: tuple[str, ...] = (),
        description_prefix: str = "LLM 申请执行工具,需要你确认",
    ) -> None:
        self._project_root = project_root.expanduser().resolve()
        # 白名单前缀集合(以 / 结尾便于 startswith 比较)
        self._whitelist_prefixes: tuple[str, ...] = (
            str((self._project_root / ".nexus").resolve()) + "/",
            *(str((Path.home() / ".nexus" / sub).resolve()) + "/" for sub in self._USER_WHITELIST_SUBDIRS),
        )
        # protected_paths 走 str 比较;resolve 后比较避免 symlink 漂移
        self._protected = {str(Path(p).expanduser().resolve()) for p in protected_paths}
        self._description_prefix = description_prefix

    # ------------------------------------------------------------------
    # 路径判定
    # ------------------------------------------------------------------

    def _is_whitelisted(self, target: str) -> bool:
        """目标路径是否在白名单内(直接放行,无 HITL)。"""
        resolved = self._safe_resolve(target)
        if resolved is None:
            return False
        # macOS 上 /tmp → /private/tmp 这种 symlink 也算命中(虽然 /tmp 是
        # dangerous,不在这条判断里)
        return any(resolved.startswith(prefix) for prefix in self._whitelist_prefixes)

    def _is_dangerous(self, target: str) -> bool:
        """目标路径是否在系统危险路径集合(直接 deny,不弹 HITL)。"""
        resolved = self._safe_resolve(target)
        if resolved is None:
            # 解析失败 → 当 dangerous 拒绝(更安全)
            return True
        return any(resolved.startswith(prefix) for prefix in self._DANGEROUS_PREFIXES)

    def _is_protected(self, target: str) -> bool:
        """目标路径是否在 QualityGate 负责的 AGENTS.md 受保护集合内。

        这些路径**不**被本中间件拦截(避免双重弹窗)。
        """
        resolved = self._safe_resolve(target)
        if resolved is None:
            return False
        return resolved in self._protected

    @staticmethod
    def _safe_resolve(target: str) -> str | None:
        """把路径解析成绝对路径,失败返回 ``None``。"""
        try:
            return str(Path(target).expanduser().resolve())
        except (OSError, RuntimeError):
            return None

    # ------------------------------------------------------------------
    # HITL 弹窗 payload 构造
    # ------------------------------------------------------------------

    def _build_hitl_request(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """构造 langchain HITL 标准格式 payload。

        返回值由 :func:`langgraph.types.interrupt` 抛出去,WS 端
        :func:`nexus.backend.api.ws.finalize._serialize_hitl_request` 读
        ``action_requests`` / ``description`` / ``args``,直接复用。
        """
        tool_name = str(tool_call.get("name", "unknown"))
        args = tool_call.get("args", {}) or {}
        target_path = _extract_target_path(args) or "(未知路径)"
        content = _extract_content(args)
        preview = (content[:200] + "...") if len(content) > 200 else content

        description = f"{self._description_prefix}\n工具:{tool_name}\n目标:{target_path}\n预览:{preview}"

        action_request = {
            "name": tool_name,
            "args": args,
            "description": description,
        }
        review_config = {
            "action_name": tool_name,
            # 与 HumanInTheLoopMiddleware 一致,提供 approve / reject 两个决策
            "allowed_decisions": ["approve", "reject"],
        }
        return {
            "action_requests": [action_request],
            "review_configs": [review_config],
        }

    # ------------------------------------------------------------------
    # 拦截钩子
    # ------------------------------------------------------------------

    def _should_interrupt(self, tool_call: dict[str, Any]) -> bool:
        """判定这次工具调用是否需要触发 HITL 弹窗。

        命中条件(全部满足):
          1. 是写工具(``_is_write_tool``)
          2. 能抽出目标路径
          3. 目标路径不在白名单(``{project_root}/.nexus/**`` + 用户级子目录)
          4. 目标路径不在 QualityGate 负责的 AGENTS.md 受保护集合
          5. 目标路径不在系统危险路径(危险路径走 deny,不弹 HITL)
        """
        tool_name = tool_call.get("name", "")
        if not _is_write_tool(tool_name):
            return False
        args = tool_call.get("args", {}) or {}
        target = _extract_target_path(args)
        if not target:
            return False
        if self._is_whitelisted(target):
            return False
        if self._is_protected(target):
            return False
        if self._is_dangerous(target):
            return False
        return True

    def _make_reject_message(self, tool_call: dict[str, Any], reason: str) -> ToolMessage:
        """构造 reject 决策对应的 ToolMessage(status='error')。

        langgraph 把 interrupt 的 resume value 通过 :class:`Command` 传回
        节点;本中间件第一次执行到 interrupt() 会重新进入(节点从头跑),
        此时用 NodeInterrupt 把 reject 转成 ToolMessage 错误回 LLM,触发
        LLM 反思。详见 :func:`wrap_tool_call` 的 resume 分支。
        """
        return ToolMessage(
            content=f"[HITL 拒绝] {reason}",
            tool_call_id=tool_call.get("id", ""),
            name=tool_call.get("name", ""),
            status="error",
        )

    def _make_deny_message(self, tool_call: dict[str, Any]) -> ToolMessage:
        """构造 dangerous 路径拒绝对应的 ToolMessage(status='error')。

        与 reject 不同的是,deny 不走 interrupt 链路,LLM 立刻看到错误并
        自主换路径(典型场景:LLM 想写 ``/tmp/foo.md`` → 看到
        ``permission denied`` → 改写 ``~/.nexus/outputs/foo.md``)。
        """
        target = _extract_target_path(tool_call.get("args", {}) or {}) or "(未知路径)"
        return ToolMessage(
            content=(
                f"[HITL 阻断] permission denied: 系统级路径 ``{target}`` "
                f"禁止写入。请改写到 ``~/.nexus/outputs/`` 之类的安全目录。"
            ),
            tool_call_id=tool_call.get("id", ""),
            name=tool_call.get("name", ""),
            status="error",
        )

    def _should_deny(self, tool_call: dict[str, Any]) -> bool:
        """判定这次工具调用是否应该直接 deny(返回错误 ToolMessage)。

        命中条件(全部满足):
          1. 是写工具
          2. 能抽出目标路径
          3. 目标路径是系统级危险路径
          4. **不在**白名单(白名单覆盖 /private 之类 symlink 解析后位置)
        """
        tool_name = tool_call.get("name", "")
        if not _is_write_tool(tool_name):
            return False
        args = tool_call.get("args", {}) or {}
        target = _extract_target_path(args)
        if not target:
            return False
        if self._is_whitelisted(target):
            return False
        return self._is_dangerous(target)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """同步入口:拦截非白名单写工具,触发 ``GraphInterrupt``。

        三态分流(顺序敏感):
          1. **白名单** → handler(request) 直接放行
          2. **危险路径**(系统级) → 直接 deny,返回 ``ToolMessage(error)``
          3. **受保护**(AGENTS.md) → handler 透传,QualityGate 评估
          4. **其它非白名单**(项目源码等) → 调 ``interrupt()`` 触发 HITL

        实现要点:
          - HITL 第一次执行(无 resume):调 ``interrupt(payload)`` 直接抛
            ``GraphInterrupt``,被 WS 端 :func:`_run_agent_streaming` 捕获,
            发 ``confirmation_request`` 帧。
          - HITL 第二次执行(用户已 approve / reject):``interrupt(payload)``
            不抛,而是返回用户决策。approve → 透传 handler;reject → 构造
            ``ToolMessage(status="error")`` 回 LLM 触发反思。
        """
        tool_call = request.tool_call
        if self._should_deny(tool_call):
            return self._make_deny_message(tool_call)
        if not self._should_interrupt(tool_call):
            return handler(request)

        hitl_request = self._build_hitl_request(tool_call)
        # 关键:interrupt() 在第一次执行抛 GraphInterrupt;在用户回复后
        # 重入节点,这次返回用户决策 dict({"decisions": [...]})。
        decisions: list[dict[str, Any]] = interrupt(hitl_request)["decisions"]  # type: ignore[index]
        if not decisions:
            return self._make_reject_message(tool_call, "用户决策列表为空")

        decision = decisions[0]
        decision_type = decision.get("type")
        if decision_type == "approve":
            return handler(request)
        # reject / edit / respond 一律视为拒绝(本中间件暂不支持编辑参数)
        reason = decision.get("message") or "用户拒绝执行此工具调用"
        return self._make_reject_message(tool_call, reason)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """异步入口:与同步版语义一致,但用 await 链。

        deepagents 0.5.x 主路径走 awrap_tool_call(FastAPI/uvicorn 全 async),
        此方法只在同步上下文(单测 / 同步脚本)被 :meth:`wrap_tool_call` 替代。
        """
        tool_call = request.tool_call
        if self._should_deny(tool_call):
            return self._make_deny_message(tool_call)
        if not self._should_interrupt(tool_call):
            return await handler(request)

        hitl_request = self._build_hitl_request(tool_call)
        decisions: list[dict[str, Any]] = interrupt(hitl_request)["decisions"]  # type: ignore[index]
        if not decisions:
            return self._make_reject_message(tool_call, "用户决策列表为空")

        decision = decisions[0]
        decision_type = decision.get("type")
        if decision_type == "approve":
            return await handler(request)
        reason = decision.get("message") or "用户拒绝执行此工具调用"
        return self._make_reject_message(tool_call, reason)


__all__ = ["PathAwareHITLMiddleware"]
