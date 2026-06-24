"""StreamGuard：可恢复的流式事件守卫。

设计目标：
  - 把"流式调用 + 失败重试 + 事件去重"封装到一个统一的包装层。
  - 给每个事件附加进程内单调递增的 ``event_id``，便于客户端去重。
  - 失败时以"幂等重试"语义从上游 astream_events 重新拉取一整段流，
    不去尝试从 token 级别续传（DeepAgents 内部状态不可续传，
    真正的 checkpoint 续传是 Phase 3 以后的事）。
  - 重试用尽时 yield 一个 ``type=error`` 事件，**不抛异常**，
    让上层 WebSocket 层有统一的处理路径。
  - 不可重试错误（auth / bad_request / context_length）也 yield
    error 事件，不浪费重试次数。
  - langgraph ``GraphInterrupt`` (HITL 中断) **不**走错误路径,而是
    透传到外层,让 ``_run_agent_streaming`` 翻译成 confirmation_request。

Phase 1 简化模型：
  - ``astream_events`` 是"工厂"，每次重试都重新调一次（不是同一个
    generator 续传）。工厂可返回 async iterator（标准用法）或 coroutine
    （仅 raise 的最简形式），两者都支持。
  - ``event_id`` 是**进程内单调递增**的整数，跨重试也连续。
  - 错误事件中的 ``replay_from_event_id`` 告诉客户端"当前 stream
    截止此处所有事件已发过，去重时跳过这些 id"，即失败前已经 yield
    给客户端的最大 event_id。
  - 上游 LLM 必须支持幂等（或至少有界），这是该简化模型的硬要求。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langgraph.errors import GraphInterrupt

from ..llm.errors import ClassifiedError, LLMErrorKind, classify
from ..llm.policies import RetryPolicy

__all__ = ["StreamGuard"]


logger = logging.getLogger(__name__)


# Wire 上 error 事件的 error_code 基础名（不带 _exhausted 后缀）。
_ERROR_RATE_LIMIT = "rate_limit"
_ERROR_TIMEOUT = "timeout"
_ERROR_AUTH = "auth"
_ERROR_BAD_REQUEST = "bad_request"
_ERROR_CONTEXT_LENGTH = "context_length"
_ERROR_CONTENT_FILTER = "content_filter"
_ERROR_UNKNOWN = "unknown"

# 工厂返回值的合法类型：async iterator 或 awaitable。
EventDict = dict[str, Any]
AstreamFactory = Callable[..., AsyncIterator[EventDict] | Awaitable[Any]]


def _map_error_code(kind: LLMErrorKind) -> str:
    """把 :class:`LLMErrorKind` 映射到 wire 上的 error_code 基础名。

    重试**用尽**时由 :meth:`StreamGuard._make_error_event` 追加
    ``_exhausted`` 后缀；不可重试错误直接用基础名。
    """
    mapping = {
        LLMErrorKind.RATE_LIMIT: _ERROR_RATE_LIMIT,
        LLMErrorKind.TIMEOUT: _ERROR_TIMEOUT,
        LLMErrorKind.AUTH: _ERROR_AUTH,
        LLMErrorKind.BAD_REQUEST: _ERROR_BAD_REQUEST,
        LLMErrorKind.CONTEXT_LENGTH: _ERROR_CONTEXT_LENGTH,
        LLMErrorKind.CONTENT_FILTER: _ERROR_CONTENT_FILTER,
        LLMErrorKind.UNKNOWN: _ERROR_UNKNOWN,
    }
    return mapping.get(kind, _ERROR_UNKNOWN)


class StreamGuard:
    """包装 ``astream_events``，提供可恢复的流式调用。

    状态：纯包装，**不持久化**任何状态。``event_id`` 是进程内单调递增的整数，
    一个 ``StreamGuard`` 实例的多次 ``astream_events`` 调用共享同一计数器。
    若需要按会话隔离，应为每个会话构造独立实例。

    Attributes:
        stats: 进程内观测计数器 ``{"retries": int, "fallbacks": int,
            "events_emitted": int}``，仅用于可观测性，不参与控制流。
    """

    def __init__(
        self,
        astream_events: AstreamFactory,
        retry_policy: RetryPolicy | None = None,
        max_total_retries: int = 2,
    ) -> None:
        """构造 StreamGuard。

        Args:
            astream_events: 上游 async generator 工厂（每次重试时会重新调用一次）。
                工厂调用结果可以是 ``AsyncIterator``（标准用法）或 ``Awaitable``
                （仅 raise 的最简形式，如 mock）。
            retry_policy: 重试判定策略；为 ``None`` 时使用默认值。
            max_total_retries: 最大重试次数（不含首次），``0`` 表示不重试。

        Raises:
            ValueError: ``max_total_retries < 0``。
        """
        if max_total_retries < 0:
            raise ValueError("max_total_retries 必须 >= 0")
        self._astream_events = astream_events
        self._retry_policy = retry_policy or RetryPolicy()
        self._max_total_retries = max_total_retries
        self._event_id = 0
        self._stats: dict[str, int] = {
            "retries": 0,
            "fallbacks": 0,
            "events_emitted": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        """返回 stats 字典的**拷贝**，外部修改不影响内部状态。"""
        return dict(self._stats)

    async def astream_events(self, input: Any, **kwargs: Any) -> AsyncIterator[EventDict]:
        """流式生成事件，带 ``event_id`` 和错误处理。

        每个事件 dict 至少包含:
          - ``event_id``: int，进程内单调递增。
          - (其他上游字段透传)

        错误事件格式::

            {
                "type": "error",
                "event_id": int,
                "error_code": str,  # rate_limit / timeout / auth / ...
                "message": str,
                "replay_from_event_id": int,
            }

        重试用尽时 ``error_code`` 追加 ``_exhausted`` 后缀
        （如 ``rate_limit_exhausted``）。

        Args:
            input: 透传给上游 ``astream_events`` 的输入。
            **kwargs: 透传给上游 ``astream_events`` 的额外参数。

        Yields:
            事件 dict，绝不抛异常（错误以 ``type=error`` 事件表达）。
        """
        attempt = 0

        while True:
            try:
                async for event in _call_factory(self._astream_events, input, kwargs):
                    self._event_id += 1
                    self._stats["events_emitted"] += 1
                    # 复制避免污染上游对象
                    enriched = dict(event)
                    enriched["event_id"] = self._event_id
                    yield enriched
                # 正常流完，返回退出
                return
            except GraphInterrupt:
                # langgraph 图挂起(HITL 中断)不是错误,透传出去让上层
                # ``_run_agent_streaming`` 翻译成 confirmation_request 帧。
                # GraphInterrupt 继承 GraphBubbleUp,本就是 langgraph 设计
                # 的"应被外层捕获"协议——StreamGuard 不应把它当 unknown
                # error 吞掉 yield 一个 error 事件。
                raise
            except Exception as exc:  # noqa: BLE001 — 边界统一收口
                classified = exc if isinstance(exc, ClassifiedError) else classify(exc)

                # 不可重试错误（auth / bad_request / context_length）：
                # 直接 yield error，不重试、不消耗重试额度。
                if not classified.retryable:
                    yield self._make_error_event(
                        error_code=_map_error_code(classified.kind),
                        message=classified.message,
                        events_before_failure=self._event_id,
                    )
                    return

                # 已用尽最大重试次数：yield error（带 _exhausted 后缀），不抛。
                if attempt >= self._max_total_retries:
                    yield self._make_error_event(
                        error_code=_map_error_code(classified.kind) + "_exhausted",
                        message=(f"重试 {attempt} 次后仍失败: {classified.message}"),
                        events_before_failure=self._event_id,
                    )
                    return

                # 进入重试
                attempt += 1
                self._stats["retries"] += 1
                logger.info(
                    "StreamGuard retry %d/%d after %s: %s",
                    attempt,
                    self._max_total_retries,
                    classified.kind,
                    classified.message,
                )
                # 退避用 RetryPolicy.compute_delay（带 jitter）
                delay = self._retry_policy.compute_delay(attempt - 1)
                if delay > 0:
                    await asyncio.sleep(delay)
                # 下次循环重新调 astream_events（幂等重试）

    def _make_error_event(
        self,
        error_code: str,
        message: str,
        events_before_failure: int,
    ) -> EventDict:
        """构造一个错误事件，event_id 同步自增。

        Args:
            error_code: 错误码字符串（已包含 ``_exhausted`` 后缀，如适用）。
            message: 人类可读错误描述。
            events_before_failure: 失败前已 yield 给客户端的事件总数。
        """
        self._event_id += 1
        self._stats["events_emitted"] += 1
        return {
            "type": "error",
            "event_id": self._event_id,
            "error_code": error_code,
            "message": message,
            "replay_from_event_id": events_before_failure,
        }


async def _call_factory(
    factory: AstreamFactory,
    input: Any,
    kwargs: dict[str, Any],
) -> AsyncIterator[EventDict]:
    """调用工厂并产出它返回的事件，统一处理"返回 async iterator"和
    "返回 awaitable"两种工厂形态。

    实现：把工厂的返回值统一视作 ``AsyncIterator``，如果实际是 coroutine
    就包一个最小的 async iterator，让首次 ``__anext__`` 时触发 await。
    """
    result: Any = factory(input, **kwargs)
    if asyncio.iscoroutine(result):
        # 工厂是普通 async function（没 yield）：await 触发函数体；
        # 若 raise，异常会从 await 抛出被外层 except 捕获；
        # 若正常 return，本流视为空（无事件可产出）。
        await result
        return
    # 否则假定是 AsyncIterator（标准 async generator 用法）
    async for event in result:
        yield event
