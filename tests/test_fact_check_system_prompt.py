"""FACT_CHECK_CONSTRAINT 注入测试 —— Task 16。

守 3 条不变量:
  1. 约束字符串本身可读、信息完整(包含 4 个工具名 + 关键关键词)
  2. ``dynamic_identity_middleware`` 把约束夹到 FACT 块之后、static
     prompt 之前(四层三明治)
  3. sm_content 两种分支(空 / 非空)都正确放置
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from nexus.backend.fact_check.prompt_constraint import (
    FACT_CHECK_CONSTRAINT,
    render_fact_check_constraint,
)
from nexus.backend.middleware.dynamic_identity import dynamic_identity_middleware

# -------- 不变量 1:字符串本身 --------


def test_constraint_constant_exists_and_informative() -> None:
    """FACT_CHECK_CONSTRAINT 必须是 string 且包含 4 个工具名 + 关键词。"""
    assert isinstance(FACT_CHECK_CONSTRAINT, str)
    assert len(FACT_CHECK_CONSTRAINT) > 50, f"约束字符串太短 ({len(FACT_CHECK_CONSTRAINT)} 字符),疑似空模板"

    # 4 个工具名都必须在约束里出现 —— 这是约束的根本目的(提示 LLM 用工具)
    for tool in ("today", "weekday_of", "next_n_days", "verify_claims"):
        assert tool in FACT_CHECK_CONSTRAINT, f"缺少工具名 {tool!r},LLM 无法对照调工具。约束: {FACT_CHECK_CONSTRAINT!r}"

    # 必须显式禁止心算星期 + 必须显式提示 verify 校验
    assert "星期" in FACT_CHECK_CONSTRAINT, "缺少'星期'关键词,无法禁止心算 mod 7"
    assert "verify" in FACT_CHECK_CONSTRAINT.lower(), "缺少 verify 关键词,LLM 看不到必须调 verify_claims 的提示"


def test_render_returns_constant() -> None:
    """render_fact_check_constraint() 必须返回 FACT_CHECK_CONSTRAINT 本身。"""
    assert render_fact_check_constraint() == FACT_CHECK_CONSTRAINT


# -------- 不变量 2 + 3:通过 middleware 注入到 system_message --------


def _make_request(user_text: str, sm_content: str | None = "原始静态 prompt") -> ModelRequest:
    """构造 ModelRequest,模拟 dynamic_identity_middleware 入口。"""

    class _StubModel(FakeChatModel):
        def invoke(self, *args, **kwargs):  # noqa: ARG002
            return AIMessage(content="(stub)")

    sm = SystemMessage(content=sm_content) if sm_content is not None else None
    return ModelRequest(
        model=_StubModel(),
        messages=[HumanMessage(content=user_text)],
        system_message=sm,
    )


def _capture_sm_content(req: ModelRequest) -> str:
    """调 middleware 把注入后的 system_message.content 抽出来。"""

    async def fake_handler(r: ModelRequest) -> AIMessage:
        captured["content"] = r.system_message.content if r.system_message else None
        return AIMessage(content="(captured)")

    captured: dict[str, str | None] = {}
    asyncio.run(dynamic_identity_middleware.awrap_model_call(req, fake_handler))
    return captured["content"] or ""


def test_constraint_injected_into_system_message_when_empty_branch() -> None:
    """Bug A 防御分支:sm_content=None / "" 时,FACT_CHECK_CONSTRAINT 必须被夹进四层三明治。"""
    captured_active = {
        "name": "test-model",
        "vendor": "test-vendor",
        "is_active": True,
        "api_base": "https://example.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        # sm_content=None 模拟 deepagents 真实运行时行为(Bug A)
        req = _make_request("明天是哪天", sm_content=None)
        content = _capture_sm_content(req)

    # 1. 约束字符串必须到达 LLM(整段 verbatim)
    assert "FACT_CHECK_CONSTRAINT" in content, f"FACT_CHECK_CONSTRAINT 块未注入到 system_message。实得: {content[:400]}"
    # 2. 工具名必须在 prompt 中(确认非空内容)
    for tool in ("today", "weekday_of", "next_n_days", "verify_claims"):
        assert tool in content, f"工具名 {tool!r} 不在最终 system_message 中"
    # 3. FACT 块也在(确认分支没退化)
    assert "test-model" in content, "FACT 块缺失,空分支应已被四层结构重建"


def test_constraint_injected_into_system_message_when_nonempty_branch() -> None:
    """非空分支:sm_content='原始静态 prompt' 时,四层结构仍正确(顺序保留)。"""
    captured_active = {
        "name": "nonempty-test-model",
        "vendor": "nonempty-vendor",
        "is_active": True,
        "api_base": "https://example.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("45 + 67 是多少", sm_content="UNIQUE_SM_MARKER_original_static_prompt_body")
        content = _capture_sm_content(req)

    # 1. FACT_BLOCK + FACT_CHECK + sm_content + FINAL_REMINDER 顺序
    fact_idx = content.find("nonempty-test-model")
    constraint_idx = content.find("FACT_CHECK_CONSTRAINT")
    sm_idx = content.find("UNIQUE_SM_MARKER")
    assert fact_idx >= 0, "FACT 块缺失"
    assert constraint_idx >= 0, "FACT_CHECK 块缺失"
    assert sm_idx >= 0, "static prompt 丢失"

    # 顺序恒等:FACT → FACT_CHECK → static prompt
    assert fact_idx < constraint_idx < sm_idx, (
        f"三明治顺序错乱:fact={fact_idx}, constraint={constraint_idx}, static_prompt={sm_idx}\n内容: {content[:400]}"
    )


def test_constraint_does_not_break_existing_identity_reminder() -> None:
    """验证 FACT_CHECK_CONSTRAINT 注入后,身份问题仍能触发 reminder(无回归)。"""
    captured_active = {
        "name": "reminder-test-model",
        "vendor": "reminder-vendor",
        "is_active": True,
        "api_base": "https://example.com/v1",
        "temperature": 0.7,
    }

    captured_messages: dict[str, list] = {}

    async def fake_handler(r: ModelRequest) -> AIMessage:
        captured_messages["msgs"] = list(r.messages)
        return AIMessage(content="(captured)")

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁?")
        asyncio.run(dynamic_identity_middleware.awrap_model_call(req, fake_handler))

    msgs = captured_messages.get("msgs", [])
    assert msgs, "messages 没传给 handler"
    last_human = msgs[-1]
    # HumanMessage 头被注入了 [System Reminder](身份问题触发分支)
    assert "[System Reminder" in (last_human.content or ""), (
        f"身份问题 [System Reminder] 注入回归。last message content: {last_human.content[:200]}"
    )
