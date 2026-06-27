"""韧性 LLM 调用包装。

该模块为单个 LangChain ``BaseChatModel``（如 ``ChatOpenAI``）提供
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
  - **集成契约**：本类继承 :class:`langchain_core.language_models.BaseChatModel`，
    以满足 deepagents 在 ``resolve_model`` 阶段的 ``isinstance(..., BaseChatModel)`` 检查；
    所有 bind 类方法（``bind`` / ``bind_tools`` / ``with_retry`` / ``with_fallbacks`` /
    ``with_structured_output``）都返回 :class:`ResilientRunnable`，保留韧性。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.model_profile import ModelProfile
from tenacity import (
    AsyncRetrying,
    retry_base,
    stop_after_attempt,
)

# 注意:用 ``import module`` 而非 ``from module import CONFIG``,否则测试
# 用 ``monkeypatch.setattr(nexus.backend.config, "CONFIG", fresh)`` 替换模块
# 属性时,wrapper 持有的 CONFIG 引用仍是旧 dict(绑定时拍快照)。
# 通过 ``nexus.backend.config.CONFIG`` 在调用时访问属性,才能拿到 monkeypatch 后的新值。
import nexus.backend.config as _config_mod
from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind, classify
from nexus.backend.llm.policies import (
    FallbackPolicy,
    RetryPolicy,
    TimeoutPolicy,
)

__all__ = ["ResilientRunnable", "build_resilient_llm"]


logger = logging.getLogger(__name__)


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


class ResilientRunnable(BaseChatModel):
    """具备"超时 + 重试 + 降级"能力的 ChatModel 包装。

    继承 :class:`langchain_core.language_models.BaseChatModel` 以满足
    deepagents / LangChain 生态对 ``isinstance(model, BaseChatModel)`` 的契约。
    任何 bind 类方法（``bind`` / ``bind_tools`` / ``with_retry`` /
    ``with_fallbacks`` / ``with_structured_output``）都会返回新的
    :class:`ResilientRunnable`，不会绕开本包装的韧性层。

    Attributes:
        primary: 主 LLM 实例。
        fallback: 备 LLM 实例；为 ``None`` 时不启用降级。
        retry_policy: 重试策略。
        timeout_policy: 超时策略。
        fallback_policy: 降级判定策略。
        stats: 进程内观测计数器 ``{"fallbacks": int, "retries": int}``，
            仅用于可观测性，不参与控制流。
    """

    def __init__(
        self,
        primary: BaseChatModel,
        fallback: BaseChatModel | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_policy: TimeoutPolicy | None = None,
        fallback_policy: FallbackPolicy | None = None,
    ) -> None:
        """初始化韧性 Runnable。

        Args:
            primary: 主 LLM（任何 ``BaseChatModel`` 子类）。
            fallback: 备 LLM，可为 ``None``。
            retry_policy: 重试策略。
            timeout_policy: 超时策略。
            fallback_policy: 降级判定策略。
        """
        # 调用 Pydantic ``BaseModel.__init__`` 以初始化 Pydantic 内部状态
        # （``__pydantic_fields_set__`` 等）。本类没有声明 Pydantic 字段，
        # 所有状态都通过 ``self.<attr> = ...`` 写到 ``__dict__``。
        super().__init__()
        self._primary = primary
        self._fallback = fallback
        self._retry_policy = retry_policy or RetryPolicy()
        self._timeout_policy = timeout_policy or TimeoutPolicy()
        self._fallback_policy = fallback_policy or FallbackPolicy()
        # 进程内可观测计数器：仅记录降级 / 重试次数，不参与控制流。
        # ``retries`` 由 tenacity 调度层管理（每次重试时手动 += 1），
        # ``fallbacks`` 由 :meth:`_invoke_fallback` 在降级入口处累加。
        self._stats: dict[str, int] = {
            "fallbacks": 0,
            "retries": 0,
        }

    # ------------------------------------------------------------------
    # BaseChatModel 抽象方法 / 推荐实现
    # ------------------------------------------------------------------

    @property
    def _llm_type(self) -> str:
        """返回 chat model 类型。组合 ``resilient_`` + 底层类型，便于 langsmith 识别。"""
        return "resilient_" + self._primary._llm_type

    def _get_ls_params(self, **kwargs: Any) -> dict[str, Any]:
        """透传到底层 primary：让 langsmith tracing 看到真实的 provider/model。"""
        return self._primary._get_ls_params(**kwargs)

    def _resolve_model_profile(self) -> ModelProfile | None:
        """驱动 deepagents SummarizationMiddleware 的 trigger 计算。

        WHY:deepagents ``compute_summarization_defaults`` 在 ``model.profile``
        含 ``max_input_tokens`` 时,固定用 ``trigger=("fraction", 0.85)``;
        无 profile 则 fallback 到 ``("tokens", 170000)``(对 200K 模型来说
        几乎不触发)。Nexus 把"总上下文大小"作为单一可配变量
        (NEXUS_CONTEXT_WINDOW,默认 200000),让 deepagents 自动按 0.85
        fraction 计算实际触发阈值 = ``context_window × 0.85``(默认 170K)。

        切换模型(200K / 1M / 32K)只需改 ``NEXUS_CONTEXT_WINDOW``,
        不用动代码;触发阈值自动按比例缩放。

        Returns:
            含 ``max_input_tokens`` 的 profile 字典(``ModelProfile`` 是
            ``TypedDict, total=False``,直接返回 ``dict`` 即可)。
            底层 primary 也能 override profile;此处只兜底提供 Nexus 假设值。
        """
        return {"max_input_tokens": int(_config_mod.CONFIG.get("context_window"))}

    def _generate(self, messages: list, stop=None, run_manager=None, **kwargs: Any):
        """同步 generate 路径：委托给底层 primary。公开入口走 ``ainvoke``。"""
        return self._primary._generate(messages, stop, run_manager, **kwargs)

    async def _agenerate(self, messages: list, stop=None, run_manager=None, **kwargs: Any) -> Any:
        """异步 generate 路径：委托给底层 primary。公开入口走 ``ainvoke``。"""
        return await self._primary._agenerate(messages, stop, run_manager, **kwargs)

    def _stream(self, messages: list, stop=None, run_manager=None, **kwargs: Any):
        """同步流路径：委托给底层 primary。公开入口走 ``astream``。"""
        yield from self._primary._stream(messages, stop, run_manager, **kwargs)

    async def _astream(self, messages: list, stop=None, run_manager=None, **kwargs: Any):
        """异步流路径：委托给底层 primary。公开入口走 ``astream``。"""
        async for chunk in self._primary._astream(messages, stop, run_manager, **kwargs):
            yield chunk

    # ------------------------------------------------------------------
    # 公开属性
    # ------------------------------------------------------------------

    @property
    def primary(self) -> BaseChatModel:
        """主 LLM。"""
        return self._primary

    @property
    def fallback(self) -> BaseChatModel | None:
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

    @property
    def stats(self) -> dict[str, int]:
        """返回 stats 字典的**拷贝**，外部修改不影响内部状态。

        字段：
          - ``fallbacks``：本实例被触发 fallback 的累计次数，由
            :meth:`_invoke_fallback` 在降级入口处累加。
          - ``retries``：本实例 ``ainvoke`` 路径下 tenacity 重试的累计次数。
        """
        return dict(self._stats)

    # ------------------------------------------------------------------
    # bind 类方法：必须返回 ResilientRunnable，否则韧性会旁路
    # ------------------------------------------------------------------

    def bind(self, **kwargs: Any) -> ResilientRunnable:
        """包装底层 primary.bind，确保返回值仍是 :class:`ResilientRunnable`。"""
        new_primary = self._primary.bind(**kwargs)
        return self._wrap_with(new_primary)

    def bind_tools(self, tools: Any, **kwargs: Any) -> ResilientRunnable:
        """包装底层 primary.bind_tools，常被 deepagents 用于 tool calling。"""
        new_primary = self._primary.bind_tools(tools, **kwargs)
        return self._wrap_with(new_primary)

    def with_retry(self, **kwargs: Any) -> ResilientRunnable:
        """包装底层 primary.with_retry。

        注意：LangChain 的 ``with_retry`` 跟我们的 :class:`RetryPolicy` 是不同语义；
        这里只把 langchain 的 binding 透传给底层 primary，外层仍由本类自带的
        重试/降级/超时策略统一控制。
        """
        new_primary = self._primary.with_retry(**kwargs)
        return self._wrap_with(new_primary)

    def with_fallbacks(self, fallbacks: Any, **kwargs: Any) -> ResilientRunnable:
        """包装底层 primary.with_fallbacks。

        取 ``fallbacks[0]`` 作为本类的 ``_fallback``（如果原 fallback 为 None），
        保留单级降级语义。
        """
        new_primary = self._primary.with_fallbacks(fallbacks, **kwargs)
        new_fallback = fallbacks[0] if fallbacks else None
        return self._wrap_with(new_primary, new_fallback)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> ResilientRunnable:
        """包装底层 primary.with_structured_output，确保结构化输出也走韧性层。"""
        new_primary = self._primary.with_structured_output(schema, **kwargs)
        return self._wrap_with(new_primary)

    def _wrap_with(
        self,
        new_primary: BaseChatModel,
        new_fallback: BaseChatModel | None = None,
    ) -> ResilientRunnable:
        """用新的 primary / fallback 构造新的 :class:`ResilientRunnable`，保留 policy。"""
        return ResilientRunnable(
            primary=new_primary,
            fallback=new_fallback if new_fallback is not None else self._fallback,
            retry_policy=self._retry_policy,
            timeout_policy=self._timeout_policy,
            fallback_policy=self._fallback_policy,
        )

    # ------------------------------------------------------------------
    # 公开 API：ainvoke / astream 带韧性
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
          - 用累计超时给整个流式生成器套一个上限。
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
            async for chunk in _iter_with_timeout(iterator, self._timeout_policy.per_stream):
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
        runnable: BaseChatModel,
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
            attempt_index = 0
            async for attempt in retrying:
                # 首次进入 attempt_index=0，后续每次重试 +1。
                # 必须在 ``with attempt:`` 之前累加，tenacity 把
                # ``attempt_number`` 视作"准备发起的尝试序号"。
                if attempt_index > 0:
                    self._stats["retries"] += 1
                attempt_index += 1
                with attempt:
                    try:
                        coro = runnable.ainvoke(input, **kwargs)
                        result = await asyncio.wait_for(coro, self._timeout_policy.per_call)
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
            if self._fallback is not None and self._fallback_policy.should_fallback(last_classified):
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

        进入本方法时**先**累加 ``fallbacks`` 计数：即使后续 fallback
        调用本身失败（抛 :class:`ClassifiedError`），也记一次降级触发，
        反映"已尝试切到备用模型"这一事实，便于上层可观测。
        """
        assert self._fallback is not None
        self._stats["fallbacks"] += 1
        try:
            coro = self._fallback.ainvoke(input, **kwargs)
            return await asyncio.wait_for(coro, self._timeout_policy.per_call)
        except TimeoutError as exc:
            raise classify(exc) from exc
        except ClassifiedError:
            raise
        except Exception as exc:  # noqa: BLE001 — 边界收口
            raise classify(exc) from exc


async def _iter_with_timeout(iterator: AsyncIterator[Any], timeout: float) -> AsyncIterator[Any]:
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
    primary: BaseChatModel,
    fallback: BaseChatModel | None = None,
    retry: RetryPolicy | None = None,
    timeout: TimeoutPolicy | None = None,
    fallback_policy: FallbackPolicy | None = None,
) -> ResilientRunnable:
    """构造一个可重试 + 可降级 + 可超时的 LLM 包装。

    Args:
        primary: 主 LLM（任何 ``BaseChatModel`` 子类）。
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
        retry_policy=retry or RetryPolicy(),
        timeout_policy=timeout or TimeoutPolicy(),
        fallback_policy=fallback_policy or FallbackPolicy(),
    )
