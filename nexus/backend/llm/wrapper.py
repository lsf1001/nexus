"""韧性 LLM 调用包装。

该模块为单个 LLM（支持 LangChain ``Runnable`` 协议）提供
"超时 + 重试 + 降级" 三件套韧性能力，是 Phase 1 容错链的核心。

设计目标：
  - 对调用方隐藏 OpenAI / 其它 SDK 的异常：所有错误都会被
    :func:`nexus.backend.llm.errors.classify` 统一收口为 :class:`ClassifiedError`。
  - 重试策略由 :class:`RetryPolicy` 描述，本模块只负责调度。
  - 降级链由 :class:`FallbackPolicy` 描述，但 wrapper 只支持单级 fallback
    （primary -> fallback），更复杂的多级链由上层在调用前把 fallback
    串起来；这与 plan 阶段要求一致。
  - 流式调用 ``astream`` 不在 wrapper 内重试（mid-stream 错误语义复杂），
    由后续 StreamGuard（Task 1.7）负责；wrapper 只给整次流加超时。
  - 不强制实现 LangChain :class:`Runnable` 全部协议：仅暴露 ``ainvoke``
    和 ``astream`` 两个最常用的入口，保持接口紧凑。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from tenacity import (
    AsyncRetrying,
    retry_base,
    stop_after_attempt,
)

from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind, classify
from nexus.backend.llm.policies import (
    FallbackPolicy,
    RetryPolicy,
    TimeoutPolicy,
)

__all__ = ["ResilientRunnable", "build_resilient_llm"]


logger = logging.getLogger(__name__)


@runtime_checkable
class _SupportsAinvoke(Protocol):
    """最小可调用协议：只需要 ``ainvoke`` / ``astream``。"""

    async def ainvoke(self, input: Any, **kwargs: Any) -> Any: ...

    def astream(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]: ...


# ``Runnable`` 别名：避免强依赖 langchain.core 的具体类型，便于单元测试用 MagicMock 替代。
Runnable = _SupportsAinvoke


class _ClassifiedRetry(retry_base):
    """根据 :class:`RetryPolicy.should_retry` 决定是否继续重试。"""

    def __init__(self, policy: RetryPolicy) -> None:
        self._policy = policy

    def __call__(self, retry_state: Any) -> bool:  # type: ignore[override]
        outcome = retry_state.outcome
        if outcome is None or outcome.exception is None:
            return False
        exc = outcome.exception()
        classified = exc if isinstance(exc, ClassifiedError) else classify(exc)
        # tenacity 的 attempt_number 从 1 开始；policy 用 0 起始的 attempt
        attempt = retry_state.attempt_number - 1
        return self._policy.should_retry(attempt, classified)


class _PolicyBasedWait:
    """把 :meth:`RetryPolicy.compute_delay` 适配为 tenacity 的 ``wait`` 接口。"""

    def __init__(self, policy: RetryPolicy) -> None:
        self._policy = policy

    def __call__(self, retry_state: Any) -> float:
        attempt = retry_state.attempt_number - 1
        return self._policy.compute_delay(attempt)


class ResilientRunnable:
    """具备"超时 + 重试 + 降级"能力的 Runnable 包装。

    Attributes:
        primary: 主 LLM 实例（具备 ``ainvoke`` / ``astream``）。
        fallback: 备 LLM 实例；为 ``None`` 时不启用降级。
        retry_policy: 重试策略。
        timeout_policy: 超时策略。
        fallback_policy: 降级判定策略。
    """

    def __init__(
        self,
        primary: Runnable,
        fallback: Runnable | None,
        retry_policy: RetryPolicy,
        timeout_policy: TimeoutPolicy,
        fallback_policy: FallbackPolicy,
    ) -> None:
        """初始化韧性 Runnable。

        Args:
            primary: 主 LLM。
            fallback: 备 LLM，可为 ``None``。
            retry_policy: 重试策略。
            timeout_policy: 超时策略。
            fallback_policy: 降级判定策略。
        """
        self._primary = primary
        self._fallback = fallback
        self._retry_policy = retry_policy
        self._timeout_policy = timeout_policy
        self._fallback_policy = fallback_policy

    @property
    def primary(self) -> Runnable:
        """主 LLM。"""
        return self._primary

    @property
    def fallback(self) -> Runnable | None:
        """备 LLM，可能为 ``None``。"""
        return self._fallback

    @property
    def retry_policy(self) -> RetryPolicy:
        """重试策略。"""
        return self._retry_policy

    @property
    def timeout_policy(self) -> TimeoutPolicy:
        """超时策略。"""
        return self._timeout_policy

    @property
    def fallback_policy(self) -> FallbackPolicy:
        """降级判定策略。"""
        return self._fallback_policy

    # ------------------------------------------------------------------
    # 透明代理：未在本类显式定义的属性/方法 → 落到底层 primary
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """把未覆盖的属性访问代理到底层 ``primary``。

        作用：LangChain ``Runnable`` 协议方法（``bind`` / ``with_fallbacks``
        / ``invoke`` / ``batch`` / ``stream`` 等）以及 ``ChatOpenAI`` 自身的
        模型字段（``model_name`` / ``temperature`` 等）都不在 wrapper 里显式
        定义，但 deepagents 编排管线和现有调用方会依赖它们；通过 ``__getattr__``
        把这部分行为透传，保证集成时零感知。

        注意事项：
          - Python 只在正常属性查找失败时才调用 ``__getattr__``，所以
            ``ainvoke`` / ``astream`` 已被本类显式定义，不会被代理走。
          - ``_primary`` 等内部字段使用单下划线前缀；``__init__`` 里通过
            ``self._primary = primary`` 写入，``__getattr__`` 只在普通查找
            失败时被触发，因此不会出现"找 _primary 又走 __getattr__"的递归
            （除非真的没初始化 _primary，那种情况下原样抛 ``AttributeError``）。
          - 底层若也没有该属性，``getattr`` 自然抛 ``AttributeError``，
            上层应该让它继续抛出，**不要**返回 ``None`` 掩盖问题。

        Args:
            name: 被访问的属性名。

        Returns:
            底层 ``primary`` 对应的属性值。

        Raises:
            AttributeError: 底层也没有该属性。
        """
        # 兜底：防止 _primary 还没初始化就被 __getattr__ 命中。
        # 走 __dict__ 直接查，避免再次触发 __getattr__ 形成递归。
        primary = self.__dict__.get("_primary")
        if primary is None:
            raise AttributeError(
                f"{type(self).__name__!s} has no attribute {name!r} "
                "(primary not initialized)"
            )
        return getattr(primary, name)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def ainvoke(self, input: Any, **kwargs: Any) -> Any:
        """带超时 + 重试 + 降级的 ``ainvoke``。

        流程：
          1. 每次 ``primary.ainvoke(input)`` 用 :func:`asyncio.wait_for`
             包裹单次超时。
          2. 把任何异常（OpenAI SDK / ``ClassifiedError`` / 其它）经
             :func:`classify` 转成 :class:`ClassifiedError`。
          3. 用 tenacity :class:`AsyncRetrying` 调度重试；
             ``wait`` 复用 :meth:`RetryPolicy.compute_delay`，
             ``retry`` 由 :class:`_ClassifiedRetry` 决定。
          4. 重试耗尽时，若有 fallback 且 ``should_fallback`` 为真，
             走 fallback；fallback 内部带超时但**不**再重试
             （避免备用模型被反复请求压垮）。
          5. 都失败则抛最后一次的 :class:`ClassifiedError`。

        Args:
            input: 透传给 ``primary.ainvoke`` 的输入。
            **kwargs: 透传给 ``primary.ainvoke`` 的额外参数。

        Returns:
            任意 LLM 响应（类型由具体 LLM 决定）。

        Raises:
            ClassifiedError: 重试 / fallback 均失败时抛出。
        """
        return await self._invoke_with_retry(self._primary, input, kwargs)

    async def astream(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """带超时的 ``astream``。

        重试由 StreamGuard（Task 1.7）负责；本方法只做：
          - 用 :func:`asyncio.wait_for` 给整个流式生成器套一个上限。
          - 把流过程中抛出的异常分类成 :class:`ClassifiedError` 再抛出。
          - 不在 wrapper 内重试 mid-stream 错误。

        Args:
            input: 透传给 ``primary.astream`` 的输入。
            **kwargs: 透传给 ``primary.astream`` 的额外参数。

        Yields:
            LLM 流式产出的 chunk。

        Raises:
            ClassifiedError: 流式调用超时或被中途抛错时抛出。
        """
        # 注意：astream 重试由 StreamGuard 负责，wrapper 只做超时 + 分类。
        try:
            iterator = self._primary.astream(input, **kwargs)
            async for chunk in _iter_with_timeout(
                iterator, self._timeout_policy.per_stream
            ):
                yield chunk
        except ClassifiedError:
            raise
        except TimeoutError as exc:
            # ``classify`` 入口已覆盖 asyncio.TimeoutError → TIMEOUT。
            raise classify(exc) from exc
        except Exception as exc:  # noqa: BLE001 — 边界统一收口
            raise classify(exc) from exc

    # ------------------------------------------------------------------
    # 内部：重试 + 降级
    # ------------------------------------------------------------------

    async def _invoke_with_retry(
        self,
        runnable: Runnable,
        input: Any,
        kwargs: dict[str, Any],
    ) -> Any:
        """对单个 Runnable 执行"超时 + 重试"，耗尽后按策略切到 fallback。

        Returns:
            成功时返回 LLM 响应。

        Raises:
            ClassifiedError: 重试 / fallback 均失败时抛出。
        """
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry_policy.max_attempts),
            wait=_PolicyBasedWait(self._retry_policy),
            retry=_ClassifiedRetry(self._retry_policy),
            # ``reraise=True`` 让 stop 触发时直接把最后一次的异常抛出，
            # 便于外层 catch 后做 fallback 决策。
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    try:
                        coro = runnable.ainvoke(input, **kwargs)
                        result = await asyncio.wait_for(
                            coro, self._timeout_policy.per_call
                        )
                    except TimeoutError as exc:
                        classified = classify(exc)
                    except ClassifiedError as exc:
                        classified = exc
                    except Exception as exc:  # noqa: BLE001 — 边界收口
                        classified = classify(exc)
                    else:
                        return result
                    # 把分类后的异常抛回给 tenacity，由 _ClassifiedRetry 决定是否重试
                    raise classified
        except ClassifiedError as last_classified:
            # 重试耗尽（stop 触发 + reraise=True），尝试 fallback
            if self._fallback is not None and self._fallback_policy.should_fallback(
                last_classified
            ):
                logger.info(
                    "primary exhausted, switching to fallback: kind=%s",
                    last_classified.kind,
                )
                return await self._invoke_fallback(input, kwargs)
            raise
        # 防御性：理论上 reraise=True 时一定会从 except 出来
        raise ClassifiedError(  # pragma: no cover
            kind=LLMErrorKind.UNKNOWN,
            retryable=False,
            original=RuntimeError("retry loop exited without exception"),
            message="[unknown] retry loop exited without exception",
        )

    async def _invoke_fallback(self, input: Any, kwargs: dict[str, Any]) -> Any:
        """执行 fallback 调用：带超时，但不重试。

        不用 tenacity：备用模型一旦失败立即抛，避免反复请求把备用供应商
        也压垮。docstring 明确这一取舍。
        """
        assert self._fallback is not None
        try:
            coro = self._fallback.ainvoke(input, **kwargs)
            return await asyncio.wait_for(coro, self._timeout_policy.per_call)
        except TimeoutError as exc:
            raise classify(exc) from exc
        except ClassifiedError:
            raise
        except Exception as exc:  # noqa: BLE001 — 边界收口
            raise classify(exc) from exc


async def _iter_with_timeout(
    iterator: AsyncIterator[Any], timeout: float
) -> AsyncIterator[Any]:
    """对 async iterator 施加**累计**超时：整个流式响应超过 ``timeout`` 秒则抛 :class:`TimeoutError`。

    实现要点：
      - 记下开始时间 ``start = time.monotonic()``，预算上限 ``deadline = start + timeout``。
      - 每次取 chunk 前计算 ``remaining = deadline - time.monotonic()``，
        把这个**递减**的值传给 :func:`asyncio.wait_for`。
      - 这样做可以保证"无论 chunk 间隔多少，总耗时到 ``timeout`` 时一定被 kill"，
        严格满足 :attr:`TimeoutPolicy.per_stream` "整个流式响应的总时长上限" 的语义。
      - ``remaining <= 0`` 时直接抛 :class:`TimeoutError`（Python 3.11+ 即
        :class:`asyncio.TimeoutError` 的别名），避免发起一次必超时的等待。
      - :class:`StopAsyncIteration` 是正常结束，return 即可。
    """
    start = time.monotonic()
    deadline = start + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("per_stream total duration exceeded")
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield chunk


# ----------------------------------------------------------------------
# 工厂
# ----------------------------------------------------------------------


def build_resilient_llm(
    primary: Runnable,
    fallback: Runnable | None = None,
    retry: RetryPolicy | None = None,
    timeout: TimeoutPolicy | None = None,
    fallback_policy: FallbackPolicy | None = None,
) -> ResilientRunnable:
    """构造一个可重试 + 可降级 + 可超时的 LLM 包装。

    Args:
        primary: 主 LLM（具备 ``ainvoke`` / ``astream`` 接口即可）。
        fallback: 备 LLM，可为 ``None``。
        retry: 重试策略，默认 :class:`RetryPolicy` 的默认值。
        timeout: 超时策略，默认 :class:`TimeoutPolicy` 的默认值。
        fallback_policy: 降级判定策略；为 ``None`` 时使用默认值。

    Returns:
        配置好的 :class:`ResilientRunnable`，可调用 ``ainvoke`` / ``astream``。
    """
    return ResilientRunnable(
        primary=primary,
        fallback=fallback,
        retry_policy=retry if retry is not None else RetryPolicy(),
        timeout_policy=timeout if timeout is not None else TimeoutPolicy(),
        fallback_policy=fallback_policy if fallback_policy is not None else FallbackPolicy(),
    )
