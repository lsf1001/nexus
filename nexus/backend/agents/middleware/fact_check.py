"""Fact-check middleware for deepagents.

Scans agent model output for fact claims, runs deterministic verification,
raises :class:`FactCheckError` on conflict (fail-closed) or attaches warning
to the response payload (fail-open).

设计要点
--------

- 本中间件**只**校验 LLM 输出,不拦工具调用;工具层面的写权限管控由
  :mod:`nexus.backend.middleware.hitl` /
  :mod:`nexus.backend.middleware.dynamic_identity` 负责,职责分离。
- ``awrap_model_call`` 接口与 deepagents 0.6.x 的
  ``AgentMiddleware.awrap_model_call`` 对齐(handler 返回 ``ModelResponse``
  或 ``dict`` 都能消费);此处用 ``_extract_content`` 兼容两种形态,避免
  与 langchain 内部 message 对象耦合。
- 校验器都是**同步**纯函数(:class:`nexus.backend.fact_check.pipeline.FactCheckPipeline`),
  本中间件不需要 ``await`` 任何 IO;故整个 ``awrap_model_call`` 仍标
  ``async`` 是为了与 deepagents 中间件签名一致(deepagents 0.6.x 主路径走
  ``await handler(request)``)。
- sync 入口 ``wrap_model_call`` 不实现 —— LangChain 把 sync/async 视作两个
  分立方法,async 必须挂到 ``awrap_model_call`` 才能被 ``agent.astream()``
  发现(2026-07-13 journey-cold-start E2E 修)。
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
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any, Literal

from langchain.agents.middleware.types import AgentMiddleware, AgentState

from nexus.backend import db as _db
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


class FactCheckMiddleware(AgentMiddleware[AgentState, Any, Any]):
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

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """拦截模型输出,扫描事实声明,按 fail_strategy 抛错或附加 warning。

        WHY ``awrap_model_call``(不是 ``wrap_model_call``):LangChain 0.3+
        把 sync/async 当作两个独立方法注册到工厂。``async def wrap_model_call``
        会被识别成 sync 入口但带 async 签名,深 agents 走 ``agent.astream()``
        时父类 fallback ``raise NotImplementedError("Asynchronous implementation
        of awrap_model_call is not available.")`` —— 这正是 2026-07-13
        journey-cold-start E2E 失败的根因。

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

        t0 = time.perf_counter()
        report = self.pipeline.check(content)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        session_id, message_id = self._extract_session_context(request)

        if not report.has_conflict:
            # 通过但有声明 → 落 audit trail
            if report.claims_total > 0:
                self._persist(
                    session_id=session_id,
                    message_id=message_id,
                    status="pass",
                    score=1.0,
                    verdict="accept",
                    reasoning=f"fact-check ok ({report.claims_total} claim(s), {report.passed} passed)",
                    claims=self._serialize_claims(report.all_results),
                    results=self._serialize_claims(report.all_results),
                    latency_ms=latency_ms,
                )
            return response

        report_dict = report.to_dict()

        if self.fail_strategy == "closed":
            # 落库 → 再抛(DB 失败仅 log,不掩盖原 FactCheckError)
            self._persist(
                session_id=session_id,
                message_id=message_id,
                status="fail",
                score=0.0,
                verdict="reject",
                reasoning=f"fact-check found {len(report.conflicts)} conflict(s)",
                claims=self._serialize_claims(report.all_results),
                results=report_dict["conflicts"],
                latency_ms=latency_ms,
            )
            logger.warning(
                "FactCheckMiddleware 拦截输出：%d 个冲突",
                len(report.conflicts),
            )
            raise FactCheckError(report_dict["conflicts"])

        # fail-open：附加 warning 到 dict 响应,字符串 / 对象形态仅记日志放行
        if isinstance(response, dict):
            response["_fact_check_warnings"] = report_dict
        # fail-open 也持久化(audit trail)
        self._persist(
            session_id=session_id,
            message_id=message_id,
            status="fail",
            score=0.0,
            verdict="reject",
            reasoning=f"fact-check open-mode: {len(report.conflicts)} conflict(s)",
            claims=self._serialize_claims(report.all_results),
            results=report_dict["conflicts"],
            latency_ms=latency_ms,
        )
        logger.warning(
            "FactCheckMiddleware open 放行：%d 个冲突",
            len(report.conflicts),
        )
        return response

    @staticmethod
    def _persist(
        *,
        session_id: str | None,
        message_id: str | None,
        status: str,
        score: float,
        verdict: str,
        reasoning: str,
        claims: list[dict[str, Any]],
        results: list[dict[str, Any]],
        latency_ms: int,
    ) -> None:
        """写一行 quality_scores 记录(DB 异常仅 log,不影响主流程)。

        WHY try/except: ``save_quality_score`` 走 sqlite3 连接,可能因为磁盘满
        / 锁等待 / 权限错误抛异常。FactCheckMiddleware 处于 agent 主循环关键
        路径,DB 落库失败不能阻断 LLM 后续回复;若阻断会让 WS 流卡住,影响
        所有客户端。因此吞异常只 log。

        WHY ``import as _alias`` 而非 ``from db import save_quality_score``:
        见模块顶部 docstring 的 monkeypatch 兼容性说明 —— 测试用
        ``monkeypatch.setattr(_db, "save_quality_score", ...)`` 才能替换。
        """
        try:
            _db.save_quality_score(
                session_id=session_id or "unknown",
                message_id=message_id,
                rubric="fact_check",
                score=score,
                verdict=verdict,
                reasoning=reasoning,
                fact_check_claims=claims,
                fact_check_results=results,
                fact_check_status=status,
                fact_check_latency_ms=latency_ms,
            )
        except Exception as exc:  # noqa: BLE001 — DB 异常不能阻断主流程
            logger.warning(
                "fact-check persistence failed (status=%s, session=%s): %s",
                status,
                session_id,
                exc,
            )

    @staticmethod
    def _serialize_claims(results: list[Any]) -> list[dict[str, Any]]:
        """把 ``VerificationResult`` 列表转成 JSON-friendly dict 列表。

        ``VerificationResult`` 是 ``frozen=True`` 的 dataclass,``dataclasses.asdict``
        能递归展开 ``FactClaim`` 子 dataclass。
        """
        out: list[dict[str, Any]] = []
        for r in results:
            if hasattr(r, "__dataclass_fields__"):
                d = asdict(r)
                # 把 claim 字段压平一层,方便读
                claim = d.pop("claim", {})
                d["claim_text"] = claim.get("raw_text", "")
                d["claim_kind"] = claim.get("kind", "")
                out.append(d)
            elif isinstance(r, dict):
                out.append(dict(r))
            else:
                out.append({"repr": str(r)})
        return out

    @staticmethod
    def _extract_session_context(request: Any) -> tuple[str | None, str | None]:
        """从 deepagents AgentState 抽 ``session_id`` / ``message_id``。

        Args:
            request: ``awrap_model_call`` 的 request 参数,期望是
                ``AgentState``(dict-like,含 ``messages``)。

        Returns:
            ``(session_id, message_id)``,取不到时返回 ``(None, None)``。
            主流程会在持久化时把 ``None`` 兜底成 ``"unknown"``。
        """
        session_id: str | None = None
        message_id: str | None = None

        # request 可能是 dict(TypedDict)或 BaseModel;两者都支持 []/get
        def _safe_get(obj: Any, key: str) -> Any:
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        msgs = _safe_get(request, "messages")
        if not msgs:
            return session_id, message_id

        # 倒序找最近一条带 session_id / message_id 的消息
        for msg in reversed(msgs):
            extra = getattr(msg, "additional_kwargs", None)
            if isinstance(extra, dict):
                if session_id is None and extra.get("session_id"):
                    session_id = str(extra["session_id"])
                if message_id is None and extra.get("message_id"):
                    message_id = str(extra["message_id"])
            metadata = getattr(msg, "metadata", None)
            if isinstance(metadata, dict):
                if session_id is None and metadata.get("session_id"):
                    session_id = str(metadata["session_id"])
                if message_id is None and metadata.get("message_id"):
                    message_id = str(metadata["message_id"])
            if session_id and message_id:
                break
        return session_id, message_id

    @staticmethod
    def _extract_content(response: Any) -> str:
        """从 handler 返回值里提取文本内容。

        兼容三种形态:
          - ``str``: 直接返回
          - ``dict``: 取 ``content`` 键(``ModelResponse.to_dict()`` 风格)
          - 对象: 取 ``.content`` 属性(langchain ``AIMessage`` 风格)

        空值兜底返回 ``""``,由 ``awrap_model_call`` 视为"无文本可校验"
        直接放行。
        """
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            return response.get("content", "") or ""
        return getattr(response, "content", "") or ""


__all__ = ["FactCheckError", "FactCheckMiddleware"]
