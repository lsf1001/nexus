"""Fact-check middleware for deepagents.

Scans agent model output for fact claims, runs deterministic verification,
raises :class:`FactCheckError` on conflict (fail-closed) or attaches warning
to the response payload (fail-open).

设计要点
--------

- 本中间件**只**校验 LLM 输出,不拦工具调用;工具层面的写权限管控由
  :mod:`nexus.backend.middleware.hitl` /
  :mod:`nexus.backend.middleware.dynamic_identity` 负责,职责分离。
- ``wrap_model_call`` 接口与 deepagents 0.6.x 的
  ``AgentMiddleware.wrap_model_call`` 对齐(handler 返回 ``ModelResponse``
  或 ``dict`` 都能消费);此处用 ``_extract_content`` 兼容两种形态,避免
  与 langchain 内部 message 对象耦合。
- 校验器都是**同步**纯函数(:class:`nexus.backend.fact_check.pipeline.FactCheckPipeline`),
  本中间件不需要 ``await`` 任何 IO;故整个 ``wrap_model_call`` 仍标
  ``async`` 是为了与 deepagents 中间件签名一致(deepagents 0.6.x 主路径走
  ``await handler(request)``)。
- **fail-open 走 warning 通道**:LLM 已经生成了一段错误事实,我们既不能
  抹掉它(用户体验差),也不能直接放行(污染下游),所以把 report dict
  挂到 ``response["_fact_check_warnings"]``,由上游 WS 端决定是否在
  ``final`` 帧后追加 system note。

为什么走 ``import as _alias`` 而不是 ``from module import fetch_rate``
---------------------------------------------------------------------
deepagents 的 ``_resolve_pending_interrupts`` / monkeypatch 测试模式
(见 CLAUDE.md 记忆 ``feedback-monkeypatch-module-state``):
``from module import X`` 在 import 时绑值,monkeypatch 改不到;用
``import module as _alias`` 后通过 ``_alias.fetch_rate`` 调用,运行时
读最新值 — 才能在测试里用 ``monkeypatch.setattr(_alias, "fetch_rate",
...)`` 替换。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from nexus.backend.fact_check.pipeline import FactCheckPipeline

logger = logging.getLogger(__name__)


class FactCheckError(Exception):
    """检测到事实冲突时抛出(fail-closed 模式)。

    Attributes:
        conflicts: 来自 :meth:`FactCheckReport.to_dict` 的 ``conflicts`` 字段,
            每个元素是 ``{claim_text, kind, verdict, claimed, actual}``。
    """

    def __init__(self, conflicts: list[dict]) -> None:
        self.conflicts = conflicts
        summary = "; ".join(f"{c['kind']}: claimed {c['claimed']} actual {c['actual']}" for c in conflicts)
        super().__init__(f"Fact-check conflict: {summary}")


class FactCheckMiddleware:
    """DeepAgents 中间件：扫描模型输出中的事实声明并验证。

    Args:
        fail_strategy: ``"closed"`` 检测到冲突抛 :class:`FactCheckError`;
            ``"open"`` 检测到冲突把 report dict 挂到 ``response["_fact_check_warnings"]``
            后放行。默认 ``"closed"``(更安全,LLM 看到错误并自纠)。
        config: 透传给 :class:`FactCheckPipeline` 的可选配置,例如
            ``{"enabled_claim_types": ["date_weekday", "math"]}``。
    """

    def __init__(
        self,
        fail_strategy: Literal["closed", "open"] = "closed",
        config: dict | None = None,
    ) -> None:
        self.fail_strategy = fail_strategy
        self.pipeline = FactCheckPipeline(config=config)

    async def wrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """拦截模型输出,扫描事实声明,按 fail_strategy 抛错或附加 warning。

        流程:
          1. ``await handler(request)`` 拿到 LLM 输出(``ModelResponse`` /
             ``dict`` / ``str`` 都吃)。
          2. :meth:`_extract_content` 抽出文本字符串。
          3. :meth:`FactCheckPipeline.check` 跑确定性校验。
          4. 无冲突 → 原样返回。
          5. 有冲突 → ``fail_strategy="closed"`` 抛 :class:`FactCheckError`;
             ``fail_strategy="open"`` 把 report dict 挂到 response 后返回。
        """
        response = await handler(request)
        content = self._extract_content(response)
        if not content:
            return response

        report = self.pipeline.check(content)
        if not report.has_conflict:
            return response

        report_dict = report.to_dict()

        if self.fail_strategy == "closed":
            logger.warning(
                "FactCheckMiddleware 拦截输出：%d 个冲突",
                len(report.conflicts),
            )
            raise FactCheckError(report_dict["conflicts"])

        # fail-open：附加 warning 到 dict 响应,字符串 / 对象形态仅记日志放行
        if isinstance(response, dict):
            response["_fact_check_warnings"] = report_dict
        logger.warning(
            "FactCheckMiddleware open 放行：%d 个冲突",
            len(report.conflicts),
        )
        return response

    @staticmethod
    def _extract_content(response: Any) -> str:
        """从 handler 返回值里提取文本内容。

        兼容三种形态:
          - ``str``: 直接返回
          - ``dict``: 取 ``content`` 键(``ModelResponse.to_dict()`` 风格)
          - 对象: 取 ``.content`` 属性(langchain ``AIMessage`` 风格)

        空值兜底返回 ``""``,由 ``wrap_model_call`` 视为"无文本可校验"
        直接放行。
        """
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            return response.get("content", "") or ""
        return getattr(response, "content", "") or ""


__all__ = ["FactCheckError", "FactCheckMiddleware"]
