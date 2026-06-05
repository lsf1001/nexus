"""韧性 LLM 包装 wrapper 模块的测试。

该文件验证 ``nexus.backend.llm.wrapper`` 模块的核心契约：
  - ``ainvoke`` 路径：超时 + 重试 + fallback 链按预期工作。
  - ``astream`` 路径：单次流式调用带超时（重试由 StreamGuard 负责，wrapper 不重试 stream）。
  - ``classify`` 在边界被正确调用，原始异常不会泄漏。
  - 默认策略可生效。
  - 不可重试 / 不可 fallback 的错误种类直接抛。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from openai import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind, classify
from nexus.backend.llm.policies import RetryPolicy, TimeoutPolicy
from nexus.backend.llm.wrapper import ResilientRunnable, build_resilient_llm

# ----------------------------------------------------------------------
# 测试辅助
# ----------------------------------------------------------------------


def _make_fake_llm(side_effects: list[Any]) -> MagicMock:
    """构造一个带 ``ainvoke`` 副作用列表的 fake LLM。

    ``side_effects`` 是 ``ainvoke`` 每次被调用时依次返回/抛出的对象。
    """
    fake = MagicMock()
    fake.ainvoke = AsyncMock(side_effect=side_effects)
    return fake


def _rate_limit_error() -> RateLimitError:
    """构造一个 RateLimitError 实例。"""
    return RateLimitError(
        "rate limit exceeded",
        response=Mock(status_code=429),
        body={"error": {"message": "rate limit"}},
    )


def _auth_error() -> AuthenticationError:
    """构造一个 AuthenticationError 实例。"""
    return AuthenticationError(
        "invalid api key",
        response=Mock(status_code=401),
        body={"error": {"message": "invalid api key"}},
    )


def _context_length_error() -> BadRequestError:
    """构造一个 context_length_exceeded 错误。"""
    return BadRequestError(
        "context too long",
        response=Mock(status_code=400),
        body={"error": {"code": "context_length_exceeded", "message": "..."}},
    )


def _api_timeout_error() -> APITimeoutError:
    """构造一个 APITimeoutError 实例。"""
    return APITimeoutError("request timeout")


# ----------------------------------------------------------------------
# 默认策略
# ----------------------------------------------------------------------


class TestDefaultPolicies:
    """不显式传 retry/timeout 时，wrapper 内部使用默认策略。"""

    async def test_default_policies_apply(self) -> None:
        """不传 retry/timeout，ainvoke 成功。"""
        primary = _make_fake_llm(["ok"])
        resilient = build_resilient_llm(primary=primary)
        result = await resilient.ainvoke({"input": "hi"})
        assert result == "ok"
        assert primary.ainvoke.await_count == 1

    async def test_returned_object_has_ainvoke_and_astream(self) -> None:
        """返回的对象是 ``ResilientRunnable``，具备 ``ainvoke`` / ``astream``。"""
        primary = _make_fake_llm(["ok"])
        resilient = build_resilient_llm(primary=primary)
        assert isinstance(resilient, ResilientRunnable)
        assert callable(resilient.ainvoke)
        assert callable(resilient.astream)

    async def test_primary_ainvoke_receives_input(self) -> None:
        """ainvoke(input) 会原样转发到 primary.ainvoke。"""
        primary = _make_fake_llm(["ok"])
        resilient = build_resilient_llm(primary=primary)
        await resilient.ainvoke({"input": "hello"})
        primary.ainvoke.assert_awaited_once_with({"input": "hello"})


# ----------------------------------------------------------------------
# 重试语义
# ----------------------------------------------------------------------


class TestAinvokeRetry:
    """``ainvoke`` 路径下的重试行为。"""

    async def test_rate_limit_retries_then_succeeds(self) -> None:
        """首次 RateLimitError → 重试 → 第二次成功。"""
        primary = _make_fake_llm([
            _rate_limit_error(),
            "success_response",
        ])
        resilient = build_resilient_llm(
            primary=primary,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        result = await resilient.ainvoke({})
        assert result == "success_response"
        assert primary.ainvoke.await_count == 2

    async def test_retry_exhausted_falls_back_to_secondary(self) -> None:
        """重试 3 次 RateLimit + 有 fallback → 切到 fallback。"""
        primary = _make_fake_llm([
            _rate_limit_error(),
            _rate_limit_error(),
            _rate_limit_error(),
        ])
        fallback = _make_fake_llm(["fallback_response"])
        resilient = build_resilient_llm(
            primary=primary,
            fallback=fallback,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        result = await resilient.ainvoke({})
        assert result == "fallback_response"
        assert primary.ainvoke.await_count == 3
        assert fallback.ainvoke.await_count == 1

    async def test_retry_exhausted_no_fallback_raises_classified(self) -> None:
        """重试 3 次 RateLimit + 无 fallback → 抛 ClassifiedError(RATE_LIMIT, retryable=True)。"""
        primary = _make_fake_llm([
            _rate_limit_error(),
            _rate_limit_error(),
            _rate_limit_error(),
        ])
        resilient = build_resilient_llm(
            primary=primary,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            await resilient.ainvoke({})
        assert exc_info.value.kind == LLMErrorKind.RATE_LIMIT
        assert exc_info.value.retryable is True
        assert primary.ainvoke.await_count == 3

    async def test_fallback_does_not_retry_itself(self) -> None:
        """fallback 自身不再重试：第 1 次失败直接抛。"""
        primary = _make_fake_llm([_rate_limit_error()] * 3)
        fallback = _make_fake_llm([_rate_limit_error()])
        resilient = build_resilient_llm(
            primary=primary,
            fallback=fallback,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            await resilient.ainvoke({})
        assert exc_info.value.kind == LLMErrorKind.RATE_LIMIT
        # primary 用完 3 次，fallback 只调用 1 次
        assert primary.ainvoke.await_count == 3
        assert fallback.ainvoke.await_count == 1


# ----------------------------------------------------------------------
# 不可重试 / 不可 fallback 错误种类
# ----------------------------------------------------------------------


class TestNonRetryableErrors:
    """AUTH / CONTEXT_LENGTH 这类错误不重试、不 fallback。"""

    async def test_auth_error_no_retry_no_fallback(self) -> None:
        """AuthenticationError → 不重试不 fallback，直接抛。"""
        primary = _make_fake_llm([_auth_error()])
        fallback = _make_fake_llm(["should_not_reach"])
        resilient = build_resilient_llm(
            primary=primary,
            fallback=fallback,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            await resilient.ainvoke({})
        assert exc_info.value.kind == LLMErrorKind.AUTH
        assert exc_info.value.retryable is False
        assert primary.ainvoke.await_count == 1
        assert fallback.ainvoke.await_count == 0

    async def test_context_length_no_retry_no_fallback(self) -> None:
        """CONTEXT_LENGTH → 不重试不 fallback。"""
        primary = _make_fake_llm([_context_length_error()])
        fallback = _make_fake_llm(["should_not_reach"])
        resilient = build_resilient_llm(
            primary=primary,
            fallback=fallback,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            await resilient.ainvoke({})
        assert exc_info.value.kind == LLMErrorKind.CONTEXT_LENGTH
        assert exc_info.value.retryable is False
        assert primary.ainvoke.await_count == 1
        assert fallback.ainvoke.await_count == 0


# ----------------------------------------------------------------------
# 超时
# ----------------------------------------------------------------------


class TestTimeout:
    """``asyncio.wait_for`` 在每次 ``ainvoke`` 上都生效。"""

    async def test_three_timeouts_raises_classified_timeout(self) -> None:
        """3 次 ainvoke 都超时时 → 抛 ClassifiedError(TIMEOUT, retryable=True)。"""
        # 让 fake ainvoke 永远 sleep 到被 wait_for 砍掉
        async def _slow(_: Any) -> Any:
            await asyncio.sleep(5.0)

        primary = MagicMock()
        primary.ainvoke = AsyncMock(side_effect=_slow)

        resilient = build_resilient_llm(
            primary=primary,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
            timeout=TimeoutPolicy(per_call=0.05),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            await resilient.ainvoke({})
        assert exc_info.value.kind == LLMErrorKind.TIMEOUT
        assert exc_info.value.retryable is True
        assert primary.ainvoke.await_count == 3

    async def test_timeout_falls_back_when_available(self) -> None:
        """超时用尽 + 有 fallback → 切到 fallback（fallback 走自己的超时但不重试）。"""

        async def _slow(_: Any) -> Any:
            await asyncio.sleep(5.0)

        primary = MagicMock()
        primary.ainvoke = AsyncMock(side_effect=_slow)

        fallback = _make_fake_llm(["fallback_ok"])
        resilient = build_resilient_llm(
            primary=primary,
            fallback=fallback,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
            timeout=TimeoutPolicy(per_call=0.05),
        )
        result = await resilient.ainvoke({})
        assert result == "fallback_ok"
        assert primary.ainvoke.await_count == 3
        assert fallback.ainvoke.await_count == 1


# ----------------------------------------------------------------------
# classify 边界
# ----------------------------------------------------------------------


class TestClassifyBoundary:
    """classify 在 wrapper 边界被调用，原始异常不会泄漏。"""

    async def test_unexpected_exception_is_classified_as_unknown(self) -> None:
        """非 OpenAI 异常 → 分类为 UNKNOWN，默认重试一次。"""
        primary = _make_fake_llm([
            RuntimeError("unexpected boom"),
            "recovered",
        ])
        resilient = build_resilient_llm(
            primary=primary,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        result = await resilient.ainvoke({})
        assert result == "recovered"
        assert primary.ainvoke.await_count == 2

    async def test_classified_error_passes_through(self) -> None:
        """如果底层直接抛 ClassifiedError（已经被上层分类过），wrapper 不重复分类。"""
        # 构造一个会从 ainvoke 抛 ClassifiedError 的 fake
        fake_classified = classify(_rate_limit_error())
        primary = _make_fake_llm([fake_classified, "ok"])
        resilient = build_resilient_llm(
            primary=primary,
            retry=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        result = await resilient.ainvoke({})
        assert result == "ok"
        assert primary.ainvoke.await_count == 2


# ----------------------------------------------------------------------
# FallbackPolicy
# ----------------------------------------------------------------------


class TestFallbackPolicy:
    """显式传 ``FallbackPolicy`` 时，按策略的 ``fallback_kinds`` 决定是否降级。"""

    async def test_non_fallback_kind_raises_even_with_fallback(self) -> None:
        """BAD_REQUEST 不在 fallback_kinds 内 → 不降级，直接抛。"""
        primary = _make_fake_llm([
            BadRequestError(
                "bad",
                response=Mock(status_code=400),
                body={"error": {"message": "bad"}},
            )
        ])
        fallback = _make_fake_llm(["should_not_reach"])
        resilient = build_resilient_llm(
            primary=primary,
            fallback=fallback,
            retry=RetryPolicy(max_attempts=2, base_delay=0.001),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            await resilient.ainvoke({})
        assert exc_info.value.kind == LLMErrorKind.BAD_REQUEST
        assert fallback.ainvoke.await_count == 0


# ----------------------------------------------------------------------
# astream
# ----------------------------------------------------------------------


async def _aiter_from_list(items: list[Any]) -> Any:
    """把 list 包装成 async iterator（用于 fake ``astream``）。"""
    for item in items:
        await asyncio.sleep(0)
        yield item


class TestAstream:
    """``astream`` 路径：单次流式调用带超时，不在 wrapper 内重试。"""

    async def test_astream_yields_chunks(self) -> None:
        """astream 正常路径：把所有 chunk 原样 yield 出来。"""
        primary = MagicMock()
        primary.astream = MagicMock(return_value=_aiter_from_list(["a", "b", "c"]))
        resilient = build_resilient_llm(primary=primary)
        chunks = []
        async for chunk in resilient.astream({}):
            chunks.append(chunk)
        assert chunks == ["a", "b", "c"]

    async def test_astream_times_out_raises_classified(self) -> None:
        """astream 整个流超过 per_stream 仍无 chunk → 抛 ClassifiedError(TIMEOUT)。"""

        async def _slow_iter() -> Any:
            await asyncio.sleep(5.0)
            yield "too_late"

        primary = MagicMock()
        primary.astream = MagicMock(return_value=_slow_iter())
        resilient = build_resilient_llm(
            primary=primary,
            timeout=TimeoutPolicy(per_stream=0.05),
        )
        with pytest.raises(ClassifiedError) as exc_info:
            async for _ in resilient.astream({}):
                pass
        assert exc_info.value.kind == LLMErrorKind.TIMEOUT

    async def test_astream_propagates_classified_error(self) -> None:
        """astream 内部抛出 ClassifiedError → wrapper 透传（不重试）。"""

        async def _bad_iter() -> Any:
            yield "first"
            raise classify(_rate_limit_error())

        primary = MagicMock()
        primary.astream = MagicMock(return_value=_bad_iter())
        resilient = build_resilient_llm(primary=primary)
        received: list[Any] = []
        with pytest.raises(ClassifiedError) as exc_info:
            async for chunk in resilient.astream({}):
                received.append(chunk)
        assert received == ["first"]
        assert exc_info.value.kind == LLMErrorKind.RATE_LIMIT
