"""LLM 异常分类模块。

该模块把来自 OpenAI SDK（以及任何 LLM 客户端）的异常归一化为
:class:`ClassifiedError`，并给出"是否值得重试"的建议。

设计目标：
  - 与具体 SDK 解耦：上层调用方只需要看 `kind` 和 `retryable`。
  - 保留原始异常引用：便于日志/上报/排障。
  - 兜底保守：未识别的异常默认重试一次，避免把瞬时故障永久丢弃。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from openai import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

__all__ = [
    "LLMErrorKind",
    "ClassifiedError",
    "classify",
    "is_context_length_error",
    "is_content_filter_error",
]


# OpenAI 在 400 错误体里常用的两个细分 code（不同模型/接口可能略有差异）。
_CONTEXT_LENGTH_CODES: Final[frozenset[str]] = frozenset(
    {"context_length_exceeded", "string_above_max_length", "maximum_context_length"}
)
_CONTENT_FILTER_CODES: Final[frozenset[str]] = frozenset(
    {"content_policy_violation", "content_filter", "content_filter_restore_error"}
)


class LLMErrorKind(StrEnum):
    """LLM 异常分类枚举。"""

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    AUTH = "auth"
    BAD_REQUEST = "bad_request"
    CONTEXT_LENGTH = "context_length"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


class ClassifiedError(BaseException):
    """经过分类的 LLM 异常。

    携带：
      - ``kind``: 错误种类（见 :class:`LLMErrorKind`）。
      - ``retryable``: 上层是否值得对该错误进行重试。
      - ``original``: 原始异常对象，便于日志/排障/上报。
      - ``message``: 人类可读的错误摘要。
    """

    kind: LLMErrorKind
    retryable: bool
    original: BaseException
    message: str

    def __init__(
        self,
        kind: LLMErrorKind,
        retryable: bool,
        original: BaseException,
        message: str,
    ) -> None:
        """初始化分类后的异常。

        Args:
            kind: 错误种类。
            retryable: 是否值得重试。
            original: 原始异常。
            message: 人类可读的错误摘要。
        """
        self.kind = kind
        self.retryable = retryable
        self.original = original
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return f"{self.kind.name}: {self.message}"


def _default_retryable(kind: LLMErrorKind) -> bool:
    """根据错误种类返回默认重试建议。

    规则：
      - rate_limit / timeout / content_filter / unknown -> True
      - auth / bad_request / context_length -> False
    """
    if kind in (
        LLMErrorKind.RATE_LIMIT,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.CONTENT_FILTER,
        LLMErrorKind.UNKNOWN,
    ):
        return True
    return False


def _extract_error_code(exc: BaseException) -> str:
    """从 OpenAI 错误对象中尝试抽取 error.code / error.type。

    兼容多种 body 形态：直接 dict 包裹或通过 ``.body`` 访问。
    抽取失败或字段缺失时返回空字符串，方便上层做包含判断。
    """
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return ""
    error_section = body.get("error")
    if not isinstance(error_section, dict):
        return ""
    code = error_section.get("code") or error_section.get("type") or ""
    return str(code).lower() if code else ""


def is_context_length_error(exc: BaseException) -> bool:
    """判断异常是否为上下文长度超限。"""
    return _extract_error_code(exc) in _CONTEXT_LENGTH_CODES


def is_content_filter_error(exc: BaseException) -> bool:
    """判断异常是否为内容审核拦截。"""
    return _extract_error_code(exc) in _CONTENT_FILTER_CODES


def _build_message(kind: LLMErrorKind, exc: BaseException) -> str:
    """生成可读的错误摘要，包含错误种类和原始异常类型。"""
    base = f"{type(exc).__name__}: {exc}"
    return f"[{kind.value}] {base}"


def classify(exc: BaseException) -> ClassifiedError:
    """把任意异常归类为 :class:`ClassifiedError`。

    Args:
        exc: 任意 Python 异常。

    Returns:
        分类后的异常实例。即使 ``exc`` 已经是 :class:`ClassifiedError`，
        也会重新分类（不进入递归路径）。
    """
    if isinstance(exc, RateLimitError):
        kind = LLMErrorKind.RATE_LIMIT
    elif isinstance(exc, APITimeoutError):
        kind = LLMErrorKind.TIMEOUT
    elif isinstance(exc, AuthenticationError):
        kind = LLMErrorKind.AUTH
    elif isinstance(exc, BadRequestError):
        if is_context_length_error(exc):
            kind = LLMErrorKind.CONTEXT_LENGTH
        elif is_content_filter_error(exc):
            kind = LLMErrorKind.CONTENT_FILTER
        else:
            kind = LLMErrorKind.BAD_REQUEST
    else:
        kind = LLMErrorKind.UNKNOWN

    return ClassifiedError(
        kind=kind,
        retryable=_default_retryable(kind),
        original=exc,
        message=_build_message(kind, exc),
    )
