"""强制 knowledge / task 类问题必须调工具的 deepagents middleware。

WHY 存在:
  2026-06-29 E2E bug —— 弱模型(MiniMax-M3)拿到 yandex_search 搜索结果
  后不回答问题,复读 system prompt 硬指令("我是 Nexus,由 X 驱动...")。
  根因是 system prompt 硬指令过强,LLM 把"元力股份 能买吗"误判为身份
  问句,绕开工具调用。本中间件在 LLM 第一次响应**没有调任何工具**时,
  自动 patch 一个 ``yandex_search`` tool_call,强制 LLM 走事实检索 —
  knowledge/task 类问题不能凭训练记忆答。

WHY 用正则而非 LLM 调 LLM:
  对齐 DeepAgents 框架设计原则 —— 中间件层不该再调 LLM(IntentClassifier
  外挂是反模式,见 docs/superpowers/plans/2026-06-29-deepagents-native-refactor.md)。
  正则判定轻量、可单测、可单元回归覆盖。

DeepAgents 0.6.12 middleware 接口: ``wrap_model_call(request, handler)``,
handler 透传到 LLM 调用,本中间件拦截响应判断是否需要 patch。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


# ============ 轻量意图分类(纯函数,可单测) ============

# knowledge 类关键词:投资 / 股票 / 医疗 / 法律 / 行情 / 百科等事实查询
_KNOWLEDGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(股票|股价|股票代码|\d{6}\.SZ|\d{6}\.SH|财报|市盈率|涨停|跌停)"),
    re.compile(r"(买不买|能买|要不要买|值得买|该不该买|能卖|能不能|会不会涨|会涨|会跌)"),
    re.compile(r"(保险|医保|社保|报销|理赔|法律|律师|法院|判决|合同|条款)"),
    re.compile(r"(行情|走势|大盘|A股|港股|美股|纳斯达克|标普|BTC|eth|以太坊|比特币)"),
    re.compile(r"(今天|昨天|明天|最近|最新).*(怎么样|如何|怎样|消息|新闻)"),
)

# task 类关键词:写代码 / 做脚本 / 查资料 / 计算 / 翻译
_TASK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(写|做|改|查|搜|算|翻译|解释|分析|帮我|请)"),
    re.compile(r"(代码|code|脚本|函数|文件|目录|数据库|api)"),
    re.compile(r"(如何|怎么|怎样|为什么|是什么|区别|推荐)"),
)

# identity 类关键词:用户问"你是谁 / 叫什么 / 什么模型"
_IDENTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(你是谁|你叫什么|你用的.{0,4}模型|你用的是什么|你的名字|你是哪家)"),
    re.compile(r"(what.*your.*name|who are you)"),
)


def classify_intent_lightweight(text: str) -> str:
    """轻量意图分类:正则优先,LLM 永不介入。

    Returns:
        ``"knowledge"`` / ``"task"`` / ``"identity"`` / ``"chitchat"``。
        默认 ``"chitchat"``,对应不强制工具调用的闲聊路径。
    """
    cleaned = text.strip()
    if not cleaned:
        return "chitchat"

    for pattern in _IDENTITY_PATTERNS:
        if pattern.search(cleaned):
            return "identity"
    for pattern in _KNOWLEDGE_PATTERNS:
        if pattern.search(cleaned):
            return "knowledge"
    for pattern in _TASK_PATTERNS:
        if pattern.search(cleaned):
            return "task"
    return "chitchat"


# ============ Middleware 类 ============


def _extract_user_query(messages: Iterable[Any]) -> str:
    """从 messages 列表提取最后一条 user 消息文本作为搜索 query。"""
    last_user = ""
    for msg in messages:
        msg_type = getattr(msg, "type", None)
        if msg_type == "human" or (isinstance(msg, tuple) and len(msg) >= 1 and msg[0] == "user"):
            content = getattr(msg, "content", None)
            if content is None and isinstance(msg, tuple):
                content = msg[1]
            if isinstance(content, str) and content.strip():
                last_user = content.strip()
    return last_user


class ForceToolMiddleware(AgentMiddleware):
    """强制 ``force_intents`` 类问题的 LLM 第一次响应必须调工具。

    行为契约:
      - LLM 第一次响应**没调任何工具** → patch 一个 ``tool_name`` tool_call,
        query 取自用户最后一条消息
      - LLM 已经调了工具 → 放行,不动
      - intent 不在 ``force_intents`` 列表里 → 放行,不动
      - 用户消息为空 → 放行,不动

    WHY 单独 ``force_intents`` 字段:测试和不同业务场景可调(强模型只强制
    task 不强制 knowledge,弱模型两个都强制)。
    """

    def __init__(
        self,
        force_intents: tuple[str, ...] = ("knowledge", "task"),
        tool_name: str = "yandex_search",
    ) -> None:
        super().__init__()
        self.force_intents = force_intents
        self.tool_name = tool_name

    def wrap_model_call(self, request: ModelRequest, handler):  # type: ignore[no-untyped-def]
        """deepagents middleware 同步钩子:拦截 LLM 响应,缺工具时 patch。"""
        response = handler(request)
        intent = classify_intent_lightweight(_extract_user_query(request.messages))
        if intent not in self.force_intents:
            return response
        if getattr(response, "tool_calls", None):
            return response

        user_query = _extract_user_query(request.messages)
        if not user_query:
            return response

        logger.info(
            "ForceToolMiddleware: %s 类问题无 tool_call,patch %s。q=%s",
            intent,
            self.tool_name,
            user_query[:50],
        )
        patched = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.tool_name,
                    "args": {"query": user_query},
                    "id": f"forced-{self.tool_name}",
                }
            ],
        )
        return patched

    async def awrap_model_call(self, request: ModelRequest, handler):  # type: ignore[no-untyped-def]
        """deepagents middleware 异步钩子(ws.py 走 astream,需 async)。"""
        response = await handler(request)
        intent = classify_intent_lightweight(_extract_user_query(request.messages))
        if intent not in self.force_intents:
            return response
        if getattr(response, "tool_calls", None):
            return response

        user_query = _extract_user_query(request.messages)
        if not user_query:
            return response

        logger.info(
            "ForceToolMiddleware: %s 类问题无 tool_call,patch %s。q=%s",
            intent,
            self.tool_name,
            user_query[:50],
        )
        patched = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.tool_name,
                    "args": {"query": user_query},
                    "id": f"forced-{self.tool_name}",
                }
            ],
        )
        return patched
