"""ForceToolMiddleware 行为测试。

WHY: 2026-06-29 E2E 暴露弱模型(MiniMax-M3)问投资问题不调 yandex_search,
LLM 答非所问。本中间件在 LLM 第一次响应没调工具时,自动 patch 一个
tool_call 强制 LLM 走搜索 — knowledge 类问题必须基于事实检索。

2026-06-30 修正:``force_intents`` 默认改为 ``("knowledge",)``,不再含
``task``。task 类问题工具选择多(write_file/edit_file/str_replace_editor),
让 LLM 自决更稳 — 强 patch yandex_search 会把 LLM 困在搜索循环里。

WHY 用轻量 regex 而非 LLM 调 LLM:对齐 DeepAgents 框架设计 — 中间件层
不该再调 LLM(IntentClassifier 外挂是反模式)。regex 判定轻量、可单测、
可单元回归覆盖。
"""

from __future__ import annotations

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from nexus.backend.middleware.force_tool import (
    ForceToolMiddleware,
    classify_intent_lightweight,
)

# ============ Intent 分类(纯函数)测试 ============


def test_classify_investment_question_as_knowledge() -> None:
    """投资类问题 → knowledge intent → 强制走工具。"""
    assert classify_intent_lightweight("元力股份 能买吗") == "knowledge"
    assert classify_intent_lightweight("BTC 还会涨吗") == "knowledge"
    assert classify_intent_lightweight("AAPL 财报") == "knowledge"
    assert classify_intent_lightweight("医保能报吗") == "knowledge"


def test_classify_chitchat_as_chitchat() -> None:
    """短闲聊 → chitchat → 不强制工具。"""
    assert classify_intent_lightweight("你好") == "chitchat"
    assert classify_intent_lightweight("谢谢") == "chitchat"


def test_classify_task_as_task() -> None:
    """任务类(写代码/做脚本/查资料)→ task → 强制工具。"""
    assert classify_intent_lightweight("帮我写一个 Python 函数") == "task"
    assert classify_intent_lightweight("查一下今天北京天气") == "task"


def test_classify_identity_questions() -> None:
    """身份问句 → identity → 不强制工具。"""
    assert classify_intent_lightweight("你是谁") == "identity"
    assert classify_intent_lightweight("你叫什么名字") == "identity"
    assert classify_intent_lightweight("你用的什么模型") == "identity"


# ============ Middleware wrap_model_call 行为测试 ============


def _make_request(user_text: str) -> ModelRequest:
    """构造测试用 ModelRequest,带 FakeChatModel 作占位。"""

    class _StubModel(FakeChatModel):
        def invoke(self, *args, **kwargs):  # noqa: ARG002
            return AIMessage(content="(stub)")

    return ModelRequest(
        model=_StubModel(),
        messages=[HumanMessage(content=user_text)],
        system_message=SystemMessage(content="你是 Nexus"),
    )


def test_knowledge_intent_without_tool_call_gets_patched() -> None:
    """knowledge 类问题,LLM 没调工具 → patch yandex_search tool_call。"""
    mw = ForceToolMiddleware(force_intents=("knowledge", "task"))

    def fake_handler(req: ModelRequest) -> AIMessage:
        return AIMessage(content="我是 Nexus,由 agnes-2.0-flash 驱动...")

    req = _make_request("元力股份 能买吗")
    response = mw.wrap_model_call(req, fake_handler)

    assert response.tool_calls, "expected patched tool_call, got none"
    assert response.tool_calls[0]["name"] == "yandex_search"
    assert "元力股份" in response.tool_calls[0]["args"]["query"]


def test_chitchat_intent_passes_through() -> None:
    """chitchat 类问题 → 不强制调工具,放行原回复。"""
    mw = ForceToolMiddleware(force_intents=("knowledge", "task"))

    def fake_handler(req: ModelRequest) -> AIMessage:
        return AIMessage(content="你好,我是 Nexus")

    req = _make_request("你好")
    response = mw.wrap_model_call(req, fake_handler)

    assert response.content == "你好,我是 Nexus"
    assert not response.tool_calls


def test_already_called_tool_passes_through() -> None:
    """LLM 已经调了工具 → 不 patch,放行原 tool_call。"""
    mw = ForceToolMiddleware(force_intents=("knowledge", "task"))

    def fake_handler(req: ModelRequest) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[{"name": "yandex_search", "args": {"query": "x"}, "id": "1"}],
        )

    req = _make_request("元力股份 能买吗")
    response = mw.wrap_model_call(req, fake_handler)

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["name"] == "yandex_search"
    assert response.tool_calls[0]["args"]["query"] == "x"


def test_identity_intent_passes_through() -> None:
    """identity 类问题 → 不强制工具,LLM 自己答。"""
    mw = ForceToolMiddleware(force_intents=("knowledge", "task"))

    def fake_handler(req: ModelRequest) -> AIMessage:
        return AIMessage(content="我是 Nexus")

    req = _make_request("你叫什么名字")
    response = mw.wrap_model_call(req, fake_handler)

    assert response.content == "我是 Nexus"
    assert not response.tool_calls


def test_task_intent_no_longer_forced_to_yandex_search() -> None:
    """2026-06-30 修正:``force_intents=("knowledge",)`` 不再含 ``task``。

    WHY:历史版本 ``("knowledge", "task")`` 把"帮我把 print 写到 foo.py"
    这类 task 也强制 patch 成 yandex_search → LLM 拿到搜索结果不知何用
    又触发新一轮"无 tool_call" → force_tool 死循环(后端日志可见同
    session 多次 patch yandex_search)。task 类工具选择多(write_file /
    edit_file / str_replace_editor),由 LLM 自决更稳。

    本测试守住不变量:task intent + LLM 没调工具 → 不 patch,放行原
    响应(可能是空 content,等待 LLM 下一轮继续决策)。
    """
    mw = ForceToolMiddleware(force_intents=("knowledge",))

    def fake_handler(req: ModelRequest) -> AIMessage:
        return AIMessage(content="")  # task 类 LLM 可能首轮空响应

    req = _make_request("帮我把 print('hello') 写到 nexus/backend/test_human.py")
    response = mw.wrap_model_call(req, fake_handler)

    # 关键断言:没被 patch
    assert not response.tool_calls, f"task 类问题不应被强制 patch yandex_search,实际: {response.tool_calls}"
    assert response.content == "", "task 类应放行原响应,不注入 tool_call"
