"""LLM 错误文案脱敏测试 (B13 安全修复)。

`nexus.backend.llm.errors._build_message` 把异常传给前端前需要把可能
泄漏的 API key / Authorization header / 长 secret 替换成 ``[REDACTED]``。
覆盖三类输入:
  1. 已知前缀 (sk-/sk-proj-/ghp_/anthropic-/xai-)
  2. 任意 32+ 位的 [A-Za-z0-9_-] 串 (兜底)
  3. 正常用户消息里的短串 / URL 不会误杀
"""

from __future__ import annotations

import re

import pytest
from openai import AuthenticationError

from nexus.backend.llm.errors import LLMErrorKind, _build_message, classify


# 已知前缀列表
@pytest.mark.parametrize(
    "leak",
    [
        "sk-" + "a" * 25,
        "sk-proj-" + "b" * 25,
        "ghp_" + "c" * 25,
        "anthropic-" + "d" * 25,
        "xai-" + "e" * 25,
    ],
)
def test_known_prefix_secrets_are_redacted(leak: str) -> None:
    """常见 LLM key 前缀应被替换为 [REDACTED]。"""
    exc = AuthenticationError(
        f"401 Unauthorized: invalid x-api-key header. value={leak}",
        response=_fake_response(),
        body={"error": {"message": "invalid x-api-key"}},
    )
    msg = _build_message(LLMErrorKind.AUTH, exc)
    assert leak not in msg
    assert "[REDACTED]" in msg


def test_long_bearer_token_is_redacted() -> None:
    """任意 32+ 位 [A-Za-z0-9_-] 串被识别为可能 secret → 替换。"""
    fake_token = "abcdef0123456789" * 2  # 32 位
    exc = AuthenticationError(
        f"Authorization: Bearer {fake_token}",
        response=_fake_response(),
        body={"error": {"message": "unauthorized"}},
    )
    msg = _build_message(LLMErrorKind.AUTH, exc)
    assert fake_token not in msg
    assert "[REDACTED]" in msg


def test_normal_text_is_not_redacted() -> None:
    """短串 / 普通 URL / 普通英文词不应被替换 (避免误杀)。"""
    text = "Failed to call model: timeout after 30s (request_id=req-abc-123)"
    exc = AuthenticationError(
        text,
        response=_fake_response(),
        body={"error": {"message": text}},
    )
    msg = _build_message(LLMErrorKind.AUTH, exc)
    assert msg == f"[auth] AuthenticationError: {text}"


def test_classify_message_is_safe_to_send_to_ws() -> None:
    """classify 出来的 ClassifiedError.message 也要过脱敏,可安全推到 WS。"""
    leak = "sk-" + "f" * 30
    exc = AuthenticationError(
        f"leaked={leak}",
        response=_fake_response(),
        body={"error": {"message": "x"}},
    )
    classified = classify(exc)
    assert leak not in classified.message
    assert "[REDACTED]" in classified.message


def test_redaction_keeps_error_kind_prefix() -> None:
    """脱敏后保留 [kind] 前缀,方便前端展示。"""
    leak = "sk-" + "g" * 25
    exc = AuthenticationError(
        f"value={leak}",
        response=_fake_response(),
        body={"error": {"message": "bad"}},
    )
    msg = _build_message(LLMErrorKind.AUTH, exc)
    assert re.match(r"^\[auth\] AuthenticationError: ", msg)
    assert msg.endswith("[REDACTED]")


# -------- helper --------


def _fake_response():
    """构造 OpenAI 错误需要的最小 response mock。"""
    from unittest.mock import MagicMock

    return MagicMock(status_code=401)
