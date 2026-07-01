"""ForceToolMiddleware content 保留回归测试。

WHY: 旧实现在 patch AIMessage 时硬编码 ``content=""``,把 LLM 原本可能
输出的自然语言回复(例如 "好的,我来帮你查")丢弃。本次修复保留原 content,
下游 consumer 仍能看到 LLM 在 tool_call 前的文本回复。
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from nexus.backend.middleware.force_tool import ForceToolMiddleware


def _make_request(user_text: str) -> ModelRequest:
    """构造测试用 ModelRequest,带 FakeChatModel 作占位。"""

    class _StubModel(FakeChatModel):
        def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
            return AIMessage(content="(stub)")

    return ModelRequest(
        model=_StubModel(),
        messages=[HumanMessage(content=user_text)],
        system_message=SystemMessage(content="你是 Nexus"),
    )


def test_sync_wrap_preserves_llm_content() -> None:
    """同步路径:LLM 写了 "好的,我来查",patch 后 content 必须保留。

    场景:user_query = "今天天气怎么样"(classifier → knowledge),
    handler 返回的 response.content = "好的,我来帮你查",tool_calls = []。
    patch 后 AIMessage.content 应保留 "好的,我来帮你查"。
    """
    mw = ForceToolMiddleware(tool_name="yandex_search", force_intents=("knowledge", "task"))

    def fake_handler(_req: ModelRequest) -> AIMessage:
        return AIMessage(content="好的,我来帮你查", tool_calls=[])

    req = _make_request("今天天气怎么样")
    patched = mw.wrap_model_call(req, fake_handler)

    assert isinstance(patched, AIMessage)
    assert patched.content == "好的,我来帮你查", f"LLM 原文 content 被丢弃: 实际 {patched.content!r}"
    assert patched.tool_calls, "patch 必须包含 tool_calls"
    assert patched.tool_calls[0]["name"] == "yandex_search"


def test_async_wrap_preserves_llm_content() -> None:
    """异步路径:与同步路径同样保留 content。"""
    import asyncio

    mw = ForceToolMiddleware(tool_name="yandex_search", force_intents=("knowledge", "task"))

    async def fake_handler(_req: ModelRequest) -> AIMessage:
        return AIMessage(content="好的,我马上查", tool_calls=[])

    req = _make_request("今天天气怎么样")
    patched = asyncio.run(mw.awrap_model_call(req, fake_handler))

    assert isinstance(patched, AIMessage)
    assert patched.content == "好的,我马上查", f"异步路径 LLM 原文 content 被丢弃: 实际 {patched.content!r}"
    assert patched.tool_calls


def test_sync_wrap_with_empty_content_still_empty() -> None:
    """边界:LLM 本来就返回空 content,patch 后仍为空(行为不变)。"""
    mw = ForceToolMiddleware(tool_name="yandex_search", force_intents=("knowledge", "task"))

    def fake_handler(_req: ModelRequest) -> AIMessage:
        return AIMessage(content="", tool_calls=[])

    req = _make_request("今天天气怎么样")
    patched = mw.wrap_model_call(req, fake_handler)

    assert patched.content == ""
    assert patched.tool_calls


def test_sync_wrap_no_intent_match_returns_original() -> None:
    """正常路径:intent 不在 force 列表里 → 直接返回原 response(content 不变)。"""
    mw = ForceToolMiddleware(tool_name="yandex_search", force_intents=("knowledge", "task"))

    def fake_handler(_req: ModelRequest) -> AIMessage:
        return AIMessage(content="你好!有什么可以帮你?", tool_calls=[])

    req = _make_request("你好")
    result = mw.wrap_model_call(req, fake_handler)

    assert isinstance(result, AIMessage)
    assert result.content == "你好!有什么可以帮你?"
    assert not result.tool_calls


def test_sync_wrap_with_existing_tool_calls_returns_original() -> None:
    """正常路径:LLM 已正确调用工具 → 不 patch,直接返回。"""
    mw = ForceToolMiddleware(tool_name="yandex_search", force_intents=("knowledge", "task"))

    def fake_handler(_req: ModelRequest) -> AIMessage:
        return AIMessage(
            content="让我查",
            tool_calls=[{"name": "yandex_search", "args": {"query": "x"}, "id": "1"}],
        )

    req = _make_request("今天天气怎么样")
    result = mw.wrap_model_call(req, fake_handler)

    assert isinstance(result, AIMessage)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["args"]["query"] == "x"
