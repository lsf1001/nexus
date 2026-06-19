"""意图识别路由:复用主 ChatModel 做 1-shot 工具调用分类。

零新依赖、零新 API key。每条 user message 多 1 次轻量 LLM 调用(< 8s 超时),
token 成本 < 200,延迟 +200-400ms。失败一律兜底 chitchat(最安全:不影响
quality gate 的 task 工具链、不影响 deepagents 路径)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

IntentKind = Literal["chitchat", "knowledge", "task"]

INTENT_CHITCHAT: IntentKind = "chitchat"
INTENT_KNOWLEDGE: IntentKind = "knowledge"
INTENT_TASK: IntentKind = "task"

# 兜底:LLM 无 tool_call / 抛异常 / 超时 → chitchat(最安全,质量门已有
# chitchat 短路,不会因为兜底误判把任务类请求当成 chitchat 走错路径——
# 反过来 task 兜底 chitchat 才会出问题,所以这里坚持 chitchat 兜底)。
DEFAULT_INTENT: IntentKind = INTENT_CHITCHAT

# 分类超时:不能阻塞主流程太久
CLASSIFY_TIMEOUT_S: float = 8.0

_CLASSIFIER_SYSTEM = """你是意图分类器。根据用户输入,只调用 1 个最合适的工具。
- route_chitchat: 闲聊/寒暄/情感陪伴/打招呼
- route_knowledge_qa: 事实/概念/查询类问题(不需工具或多步执行)
- route_task_execute: 需要调用工具/MCP/多步执行的复杂任务"""


@tool
def route_chitchat(text: str) -> str:
    """闲聊/寒暄/情感陪伴/打招呼类输入。"""
    return INTENT_CHITCHAT


@tool
def route_knowledge_qa(text: str) -> str:
    """事实/概念/查询类问题(不需要工具或多步执行)。"""
    return INTENT_KNOWLEDGE


@tool
def route_task_execute(text: str) -> str:
    """需要调用工具/MCP/多步执行的复杂任务。"""
    return INTENT_TASK


INTENT_TOOLS = [route_chitchat, route_knowledge_qa, route_task_execute]

_TOOL_TO_INTENT: dict[str, IntentKind] = {
    "route_chitchat": INTENT_CHITCHAT,
    "route_knowledge_qa": INTENT_KNOWLEDGE,
    "route_task_execute": INTENT_TASK,
}


async def classify_intent(llm: BaseChatModel, message: str) -> IntentKind:
    """复用主 ChatModel 做 1-shot 意图分类。

    Args:
        llm: 已构造的 ``BaseChatModel``(建议复用 quality pipeline 那个
            temperature=0 的 judge_llm,verdict 稳定 + 零新模型)。
        message: 用户原始消息。

    Returns:
        IntentKind 字面量。所有异常 / 无 tool_call / 未知 tool 名一律
        兜底为 ``DEFAULT_INTENT``(chitchat)并记 WARNING,不抛。
    """
    try:
        resp = await asyncio.wait_for(
            llm.bind_tools(INTENT_TOOLS).ainvoke(
                [
                    SystemMessage(content=_CLASSIFIER_SYSTEM),
                    HumanMessage(content=message),
                ]
            ),
            timeout=CLASSIFY_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — 边界统一兜底
        logger.warning("意图分类 LLM 失败,兜底 chitchat: %s", exc)
        return DEFAULT_INTENT

    tool_calls = getattr(resp, "tool_calls", None) or []
    if not tool_calls:
        logger.info("意图分类未返回 tool_call,兜底 chitchat")
        return DEFAULT_INTENT

    first = tool_calls[0]
    name = first.get("name") if isinstance(first, dict) else getattr(first, "name", "")
    intent = _TOOL_TO_INTENT.get(name or "")
    if intent is None:
        logger.warning("意图分类返回未知 tool 名: %s,兜底 chitchat", name)
        return DEFAULT_INTENT
    return intent
