"""LLM 异常分类模块的测试。

该文件验证 `nexus.backend.llm.errors` 模块的核心契约：
  - `classify(exc)` 把不同类型的 OpenAI 异常映射到 `ClassifiedError`
  - `ClassifiedError.retryable` 字段携带正确的重试建议
  - 未识别的异常会兜底为 `UNKNOWN` 且默认允许重试一次
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from openai import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from nexus.backend.llm.errors import (
    ClassifiedError,
    LLMErrorKind,
    classify,
)


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


def _timeout_error() -> APITimeoutError:
    """构造一个 APITimeoutError 实例。"""
    return APITimeoutError("request timeout")


def _bad_request_error() -> BadRequestError:
    """构造一个 BadRequestError 实例。"""
    return BadRequestError(
        "bad request",
        response=Mock(status_code=400),
        body={"error": {"message": "bad request"}},
    )


def test_rate_limit_is_retryable() -> None:
    """RateLimitError -> RATE_LIMIT，retryable=True。"""
    err = classify(_rate_limit_error())
    assert err.kind == LLMErrorKind.RATE_LIMIT
    assert err.retryable is True


def test_auth_is_not_retryable() -> None:
    """AuthenticationError -> AUTH，retryable=False。"""
    err = classify(_auth_error())
    assert err.kind == LLMErrorKind.AUTH
    assert err.retryable is False


def test_timeout_is_retryable() -> None:
    """APITimeoutError -> TIMEOUT，retryable=True。"""
    err = classify(_timeout_error())
    assert err.kind == LLMErrorKind.TIMEOUT
    assert err.retryable is True


def test_bad_request_not_retryable() -> None:
    """BadRequestError -> BAD_REQUEST，retryable=False。"""
    err = classify(_bad_request_error())
    assert err.kind == LLMErrorKind.BAD_REQUEST
    assert err.retryable is False


def test_unknown_exception_maps_to_unknown() -> None:
    """未知异常兜底为 UNKNOWN，默认允许重试一次。"""
    err = classify(ValueError("weird"))
    assert err.kind == LLMErrorKind.UNKNOWN
    assert err.retryable is True


def test_classified_error_preserves_original() -> None:
    """ClassifiedError 必须保留原始异常引用，便于上层记录/上报。"""
    original = _rate_limit_error()
    err = classify(original)
    assert err.original is original
    assert err.original is not None


def test_classified_error_message_is_readable() -> None:
    """ClassifiedError.message 必须是可读字符串，至少包含类型信息。"""
    err = classify(_auth_error())
    assert isinstance(err.message, str)
    assert err.message  # 非空


def test_classified_error_is_an_exception() -> None:
    """ClassifiedError 必须可作为异常使用（继承自 Exception，不是 BaseException）。

    关键：业务异常必须继承 :class:`Exception`，否则上层的
    ``except Exception`` 会漏掉它。
    """
    err = classify(_timeout_error())
    assert isinstance(err, Exception)
    assert isinstance(err, ClassifiedError)
    # 可正常 raise / str
    with pytest.raises(ClassifiedError):
        raise err
    assert "TIMEOUT" in str(err)


def test_kind_enum_values_are_distinct() -> None:
    """LLMErrorKind 的枚举值必须互不相同。"""
    values = {member.value for member in LLMErrorKind}
    assert len(values) == len(list(LLMErrorKind))


def test_context_length_classification() -> None:
    """BadRequestError 含 context_length_exceeded code 时归为 CONTEXT_LENGTH。"""
    exc = BadRequestError(
        "too long",
        response=Mock(status_code=400),
        body={"error": {"code": "context_length_exceeded", "message": "..."}},
    )
    err = classify(exc)
    assert err.kind == LLMErrorKind.CONTEXT_LENGTH
    assert err.retryable is False  # 重试没意义，要改 prompt


def test_content_filter_classification() -> None:
    """BadRequestError 含 content_policy_violation code 时归为 CONTENT_FILTER。"""
    exc = BadRequestError(
        "blocked",
        response=Mock(status_code=400),
        body={"error": {"code": "content_policy_violation", "message": "..."}},
    )
    err = classify(exc)
    assert err.kind == LLMErrorKind.CONTENT_FILTER
    assert err.retryable is True


def test_bad_request_with_no_code_falls_back() -> None:
    """BadRequestError body 里 code 缺失时，落到 BAD_REQUEST 兜底，不误判细分类型。"""
    exc = BadRequestError(
        "generic bad",
        response=Mock(status_code=400),
        body={"error": {"message": "no code"}},
    )
    err = classify(exc)
    assert err.kind == LLMErrorKind.BAD_REQUEST
    assert err.retryable is False


def test_bad_request_with_malformed_body_falls_back() -> None:
    """BadRequestError body 形态异常（缺 error 段）时，落到 BAD_REQUEST 兜底。"""
    # body 完全没有 error 段
    exc = BadRequestError("weird", response=Mock(status_code=400), body={"other": "shape"})
    err = classify(exc)
    assert err.kind == LLMErrorKind.BAD_REQUEST
    assert err.retryable is False
