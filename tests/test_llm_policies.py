"""LLM 策略 dataclass 模块的测试。

该文件验证 `nexus.backend.llm.policies` 模块的核心契约：
  - ``RetryPolicy.compute_delay`` 实现指数退避 + 抖动，延迟在合理范围内。
  - ``RetryPolicy.should_retry`` 按 ``max_attempts`` 和 ``retryable_kinds`` 判定。
  - ``FallbackPolicy.should_fallback`` / ``next_llm`` 控制模型链切换。
  - ``TimeoutPolicy`` 三个字段独立可控。
"""

from __future__ import annotations

import random
from unittest.mock import Mock

import pytest
from openai import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from nexus.backend.llm.errors import ClassifiedError, LLMErrorKind, classify
from nexus.backend.llm.policies import (
    FallbackPolicy,
    RetryPolicy,
    TimeoutPolicy,
)

# ----------------------------------------------------------------------
# 测试辅助：构造不同种类的 ClassifiedError
# ----------------------------------------------------------------------


def _classified_kind(kind: LLMErrorKind) -> ClassifiedError:
    """根据指定 kind 构造一个 ClassifiedError，使用 Mock 作为原始异常。"""
    return ClassifiedError(
        kind=kind,
        retryable=kind in {
            LLMErrorKind.RATE_LIMIT,
            LLMErrorKind.TIMEOUT,
            LLMErrorKind.CONTENT_FILTER,
            LLMErrorKind.UNKNOWN,
        },
        original=Mock(spec=BaseException),
        message=f"[{kind.value}] fake",
    )


def _classified_from_openai(exc: BaseException) -> ClassifiedError:
    """通过 classify() 走真实路径构造 ClassifiedError。"""
    return classify(exc)


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


def _bad_request_error() -> BadRequestError:
    """构造一个 BadRequestError 实例。"""
    return BadRequestError(
        "bad request",
        response=Mock(status_code=400),
        body={"error": {"message": "bad request"}},
    )


def _context_length_error() -> BadRequestError:
    """构造一个 context_length_exceeded 错误。"""
    return BadRequestError(
        "too long",
        response=Mock(status_code=400),
        body={"error": {"code": "context_length_exceeded", "message": "..."}},
    )


def _timeout_error() -> APITimeoutError:
    """构造一个 APITimeoutError 实例。"""
    return APITimeoutError("request timeout")


# ----------------------------------------------------------------------
# RetryPolicy.compute_delay
# ----------------------------------------------------------------------


class TestRetryPolicyComputeDelay:
    """RetryPolicy.compute_delay 的语义验证。"""

    def test_delay_grows_exponentially_without_jitter(self) -> None:
        """无抖动时，delay(0) < delay(1) < delay(2)，呈指数增长。"""
        policy = RetryPolicy(base_delay=0.1, max_delay=10.0, jitter=0.0)
        d0 = policy.compute_delay(0)
        d1 = policy.compute_delay(1)
        d2 = policy.compute_delay(2)
        assert d0 == pytest.approx(0.1)
        assert d1 == pytest.approx(0.2)
        assert d2 == pytest.approx(0.4)
        assert d0 < d1 < d2

    def test_delay_clamped_to_max(self) -> None:
        """无论 attempt 多大，compute_delay 都不会超过 max_delay。"""
        policy = RetryPolicy(base_delay=0.1, max_delay=2.0, jitter=0.0)
        for attempt in range(10):
            assert policy.compute_delay(attempt) <= 2.0

    def test_delay_with_max_jitter_still_within_ratio(self) -> None:
        """开启 jitter 后，多次采样的 delay 应落在 ±jitter 比例范围内。

        设计：base_delay * (2 ** attempt) * (1 + random.uniform(-jitter, +jitter))，
        并 clamp 到 [0, max_delay]。当 max_delay 足够大时，clamp 不生效，
        抖动范围完全由 jitter 决定。
        """
        policy = RetryPolicy(
            base_delay=1.0,
            max_delay=1000.0,
            jitter=0.2,
        )
        random.seed(42)
        # 不上 max_delay 时的期望延迟 = 1.0 * 2^attempt
        for attempt in range(3):
            base = 1.0 * (2 ** attempt)
            for _ in range(50):
                d = policy.compute_delay(attempt)
                # 抖动比例最多 ±0.2，再加上 clamp 不会更小
                assert 0.0 <= d <= base * 1.2 + 1e-9

    def test_delay_non_negative(self) -> None:
        """compute_delay 永远 >= 0，不会返回负值。"""
        policy = RetryPolicy(base_delay=0.1, max_delay=2.0, jitter=0.5)
        random.seed(0)
        for attempt in range(5):
            assert policy.compute_delay(attempt) >= 0.0

    def test_delay_distribution_within_jitter_band(self) -> None:
        """统计检验：jitter=0.0 时延迟是确定值；jitter=0.5 时多采样出现波动。"""
        fixed = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=0.0)
        assert fixed.compute_delay(2) == pytest.approx(4.0)

        jittered = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=0.5)
        random.seed(7)
        samples = {jittered.compute_delay(0) for _ in range(200)}
        # 多次采样应出现多个不同值（抖动确实有变化）
        assert len(samples) > 1


# ----------------------------------------------------------------------
# RetryPolicy.should_retry
# ----------------------------------------------------------------------


class TestRetryPolicyShouldRetry:
    """RetryPolicy.should_retry 的语义验证。"""

    def test_first_failure_with_retryable_kind_can_retry(self) -> None:
        """attempt=0, max_attempts=3，且错误种类可重试 -> 可重试。"""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.RATE_LIMIT)) is True

    def test_last_attempt_cannot_retry(self) -> None:
        """attempt=max_attempts-1 时已用尽额度 -> 不可重试。"""
        policy = RetryPolicy(max_attempts=3)
        # attempt=2 意味着已经发起过 2 次（包含首次），共 3 次 -> 用尽
        assert policy.should_retry(2, _classified_kind(LLMErrorKind.RATE_LIMIT)) is False

    def test_auth_never_retries(self) -> None:
        """AUTH 即使在 attempt=0 也不应重试（错误种类不在 retryable_kinds）。"""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.AUTH)) is False

    def test_bad_request_never_retries(self) -> None:
        """BAD_REQUEST 不在默认 retryable_kinds 内。"""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.BAD_REQUEST)) is False

    def test_context_length_never_retries(self) -> None:
        """CONTEXT_LENGTH 不在默认 retryable_kinds 内（重试没意义）。"""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.CONTEXT_LENGTH)) is False

    def test_timeout_and_rate_limit_can_retry(self) -> None:
        """TIMEOUT / RATE_LIMIT / UNKNOWN / CONTENT_FILTER 都属于默认可重试。"""
        policy = RetryPolicy(max_attempts=3)
        for kind in (
            LLMErrorKind.TIMEOUT,
            LLMErrorKind.RATE_LIMIT,
            LLMErrorKind.UNKNOWN,
            LLMErrorKind.CONTENT_FILTER,
        ):
            assert policy.should_retry(0, _classified_kind(kind)) is True, kind

    def test_real_classified_errors(self) -> None:
        """使用真实 classify() 路径下的 ClassifiedError 验证。"""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(0, _classified_from_openai(_rate_limit_error())) is True
        assert policy.should_retry(0, _classified_from_openai(_auth_error())) is False
        assert policy.should_retry(0, _classified_from_openai(_timeout_error())) is True
        assert policy.should_retry(0, _classified_from_openai(_bad_request_error())) is False
        assert policy.should_retry(0, _classified_from_openai(_context_length_error())) is False

    def test_custom_retryable_kinds(self) -> None:
        """允许通过 retryable_kinds 自定义重试种类。"""
        # 把 AUTH 加入 retryable_kinds
        policy = RetryPolicy(
            max_attempts=3,
            retryable_kinds=frozenset({LLMErrorKind.AUTH, LLMErrorKind.RATE_LIMIT}),
        )
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.AUTH)) is True
        # TIMEOUT 反而不在自定义集合中 -> 不可重试
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.TIMEOUT)) is False

    def test_max_attempts_one_means_no_retry(self) -> None:
        """max_attempts=1 时只有首次尝试，attempt=0 就已"用尽"。"""
        policy = RetryPolicy(max_attempts=1)
        assert policy.should_retry(0, _classified_kind(LLMErrorKind.RATE_LIMIT)) is False


# ----------------------------------------------------------------------
# FallbackPolicy.should_fallback
# ----------------------------------------------------------------------


class TestFallbackPolicyShouldFallback:
    """FallbackPolicy.should_fallback 的语义验证。"""

    def test_rate_limit_triggers_fallback(self) -> None:
        """RATE_LIMIT 默认在 fallback_kinds 内。"""
        policy = FallbackPolicy()
        assert policy.should_fallback(_classified_kind(LLMErrorKind.RATE_LIMIT)) is True

    def test_auth_triggers_fallback(self) -> None:
        """AUTH 默认在 fallback_kinds 内（主模型鉴权失败可换备用）。"""
        policy = FallbackPolicy()
        assert policy.should_fallback(_classified_kind(LLMErrorKind.AUTH)) is True

    def test_timeout_triggers_fallback(self) -> None:
        """TIMEOUT 默认在 fallback_kinds 内。"""
        policy = FallbackPolicy()
        assert policy.should_fallback(_classified_kind(LLMErrorKind.TIMEOUT)) is True

    def test_bad_request_does_not_trigger_fallback(self) -> None:
        """BAD_REQUEST 不应触发 fallback（应改 prompt）。"""
        policy = FallbackPolicy()
        assert policy.should_fallback(_classified_kind(LLMErrorKind.BAD_REQUEST)) is False

    def test_context_length_does_not_trigger_fallback(self) -> None:
        """CONTEXT_LENGTH 不应触发 fallback（应改 prompt）。"""
        policy = FallbackPolicy()
        assert policy.should_fallback(_classified_kind(LLMErrorKind.CONTEXT_LENGTH)) is False

    def test_custom_fallback_kinds(self) -> None:
        """允许通过 fallback_kinds 自定义允许 fallback 的种类。"""
        policy = FallbackPolicy(
            fallback_kinds=frozenset({LLMErrorKind.RATE_LIMIT}),
        )
        # AUTH 不在自定义集合中 -> 不 fallback
        assert policy.should_fallback(_classified_kind(LLMErrorKind.AUTH)) is False
        assert policy.should_fallback(_classified_kind(LLMErrorKind.RATE_LIMIT)) is True


# ----------------------------------------------------------------------
# FallbackPolicy.next_llm
# ----------------------------------------------------------------------


class TestFallbackPolicyNextLLM:
    """FallbackPolicy.next_llm 的语义验证。"""

    def test_next_from_index_zero(self) -> None:
        """chains=(A,B,C) 从 0 -> 下一个是 1。"""
        policy = FallbackPolicy(chains=("A", "B", "C"))
        idx, llm = policy.next_llm(0)
        assert idx == 1
        assert llm == "B"

    def test_next_from_last_index_returns_exhausted(self) -> None:
        """chains=(A,B,C) 从 2（最后一个）-> 耗尽，返回 (3, None)。"""
        policy = FallbackPolicy(chains=("A", "B", "C"))
        idx, llm = policy.next_llm(2)
        assert idx == 3
        assert llm is None

    def test_next_from_middle_index(self) -> None:
        """从中间索引 1 -> 下一个是 2。"""
        policy = FallbackPolicy(chains=("A", "B", "C"))
        idx, llm = policy.next_llm(1)
        assert idx == 2
        assert llm == "C"

    def test_next_beyond_last_returns_exhausted(self) -> None:
        """超出末尾（>= len(chains)）也视为耗尽。"""
        policy = FallbackPolicy(chains=("A", "B"))
        idx, llm = policy.next_llm(5)
        assert idx == 6
        assert llm is None

    def test_empty_chains_always_exhausted(self) -> None:
        """空 chains：任何索引都耗尽。"""
        policy = FallbackPolicy()
        for i in (-1, 0, 1, 100):
            idx, llm = policy.next_llm(i)
            assert llm is None
            assert idx == i + 1  # 仍是当前+1，调用方可以据此判断"再走一步还是空"

    def test_next_llm_with_real_objects(self) -> None:
        """chains 可以持有任意对象（如 ChatOpenAI 实例），不要求具体类型。"""
        a, b = Mock(name="A"), Mock(name="B")
        policy = FallbackPolicy(chains=(a, b))
        idx, llm = policy.next_llm(0)
        assert idx == 1
        assert llm is b


# ----------------------------------------------------------------------
# TimeoutPolicy
# ----------------------------------------------------------------------


class TestTimeoutPolicy:
    """TimeoutPolicy 字段与默认值的语义验证。"""

    def test_default_values(self) -> None:
        """默认值符合预期：per_step=30, per_call=120, per_stream=600。"""
        policy = TimeoutPolicy()
        assert policy.per_step == 30.0
        assert policy.per_call == 120.0
        assert policy.per_stream == 600.0

    def test_three_fields_are_independent(self) -> None:
        """三个字段独立可设。"""
        policy = TimeoutPolicy(per_step=5.0, per_call=10.0, per_stream=20.0)
        assert policy.per_step == 5.0
        assert policy.per_call == 10.0
        assert policy.per_stream == 20.0

    def test_partial_override(self) -> None:
        """只覆盖部分字段时，未指定的字段保持默认。"""
        policy = TimeoutPolicy(per_step=1.0)
        assert policy.per_step == 1.0
        assert policy.per_call == 120.0
        assert policy.per_stream == 600.0

    def test_frozen(self) -> None:
        """TimeoutPolicy 是 frozen dataclass，不可变。"""
        policy = TimeoutPolicy()
        with pytest.raises((AttributeError, Exception)):
            policy.per_step = 999.0  # type: ignore[misc]


# ----------------------------------------------------------------------
# 不可变性与默认值
# ----------------------------------------------------------------------


class TestPolicyImmutability:
    """所有策略 dataclass 应为 frozen，避免下游误改共享配置。"""

    def test_retry_policy_is_frozen(self) -> None:
        """RetryPolicy 不可变。"""
        policy = RetryPolicy()
        with pytest.raises((AttributeError, Exception)):
            policy.max_attempts = 999  # type: ignore[misc]

    def test_fallback_policy_is_frozen(self) -> None:
        """FallbackPolicy 不可变。"""
        policy = FallbackPolicy()
        with pytest.raises((AttributeError, Exception)):
            policy.chains = ("x",)  # type: ignore[misc]

    def test_retry_policy_default_kinds_is_frozenset(self) -> None:
        """RetryPolicy.retryable_kinds 默认值是不可变集合。"""
        policy = RetryPolicy()
        assert isinstance(policy.retryable_kinds, frozenset)

    def test_fallback_policy_default_kinds_is_frozenset(self) -> None:
        """FallbackPolicy.fallback_kinds 默认值是不可变集合。"""
        policy = FallbackPolicy()
        assert isinstance(policy.fallback_kinds, frozenset)
