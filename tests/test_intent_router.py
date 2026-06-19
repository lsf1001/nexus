"""意图路由器:5 个场景覆盖 happy/3 类/兜底。"""

from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from nexus.backend.intent.router import (
    DEFAULT_INTENT,
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
    classify_intent,
)


class _FakeLLM(BaseChatModel):
    """预设 tool_call / text / raise 三种响应。"""

    tool_call_name: str = ""
    text_response: str = ""
    raise_exc: BaseException | None = None
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    def bind_tools(self, tools, **kwargs):
        """真实 ChatModel 都 override bind_tools;fake 不需要做 kwargs 适配,直接返回 self。"""
        return self

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.tool_call_name:
            return AIMessage(
                content="",
                tool_calls=[{"name": self.tool_call_name, "args": {"text": "input"}, "id": "call_1"}],
            )
        return AIMessage(content=self.text_response)


async def test_classify_task_complex_prompt():
    llm = _FakeLLM(tool_call_name="route_task_execute")
    assert await classify_intent(llm, "帮我写一个 Python 函数") == INTENT_TASK
    assert llm.call_count == 1


async def test_classify_knowledge_question():
    llm = _FakeLLM(tool_call_name="route_knowledge_qa")
    assert await classify_intent(llm, "Python 是什么?") == INTENT_KNOWLEDGE


async def test_classify_chitchat_greeting():
    llm = _FakeLLM(tool_call_name="route_chitchat")
    assert await classify_intent(llm, "你好") == INTENT_CHITCHAT


async def test_classify_falls_back_when_no_tool_call():
    """LLM 仅输出文本(没调工具)时,兜底 chitchat。"""
    llm = _FakeLLM(text_response="这是个问题")
    assert await classify_intent(llm, "test") == DEFAULT_INTENT
    assert DEFAULT_INTENT == INTENT_CHITCHAT


async def test_classify_falls_back_when_llm_raises():
    """LLM 异常时,兜底 chitchat,日志 WARNING,不抛。"""
    llm = _FakeLLM(raise_exc=RuntimeError("LLM down"))
    assert await classify_intent(llm, "test") == INTENT_CHITCHAT


async def test_classify_falls_back_on_timeout(monkeypatch):
    """LLM 超时时,兜底 chitchat,不阻塞主流程。"""
    monkeypatch.setattr("nexus.backend.intent.router.CLASSIFY_TIMEOUT_S", 0.1)

    class _SlowLLM(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise NotImplementedError

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, input, config=None, stop=None, **kwargs):
            await asyncio.sleep(10)
            return AIMessage(content="")

    assert await classify_intent(_SlowLLM(), "test") == INTENT_CHITCHAT
