"""意图识别路由 —— 2026-06-29 重构后改用正则推断。

WHY 重构:
  旧版 ``classify_intent(llm, message)`` 复用主 ChatModel 做 1-shot function-calling
  分类,每次 user 消息多 1 次 LLM 调用(5s 硬限超时),延迟 +200-400ms 且
  引入 agnes 慢模型 16s+ 的不确定性。对齐 DeepAgents 框架设计原则:

    - 中间件 / 路由层**不该**再调 LLM(IntentClassifier 是反模式,见
      :mod:`docs/superpowers/plans/2026-06-29-deepagents-native-refactor.md`)
    - 主 LLM 决定 dispatch 哪个 subagent 走 :class:`SubAgent` + Task 工具
      机制(已由 deepagents 0.6.x :class:`SubAgentMiddleware` 自动注入)
    - 业务级"intent 标记"用于 DB 统计 / observability 事件,用正则同步
      推断即可,不需要 LLM 介入

WHAT 保留:
  - :data:`IntentKind` 字面量集合(``chitchat`` / ``knowledge`` / ``task``)
    — DB schema / observability 事件 / 前端分类都用
  - :func:`classify_intent` 函数名(签名改了:不再接 ``llm``,只接 ``message``)
    — 保留旧名降低改动面;测试同步更新
  - :data:`DEFAULT_INTENT` 兜底常量
  - 三个 ``INTENT_*`` 名字常量

WHAT 删除:
  - ``BaseChatModel`` / langchain ``@tool`` 装饰器 / ``INTENT_TOOLS`` /
    ``_TOOL_TO_INTENT`` 等 LLM-to-LLM 分类相关代码
  - 5s 超时 / ``CLASSIFY_TIMEOUT_S``(不再有 LLM 调用)
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

IntentKind = Literal["chitchat", "knowledge", "task"]

INTENT_CHITCHAT: IntentKind = "chitchat"
INTENT_KNOWLEDGE: IntentKind = "knowledge"
INTENT_TASK: IntentKind = "task"

# 兜底:正则无匹配 / 异常 → chitchat(最安全:不影响 deepagents SubAgent
# dispatch 路径,也不影响 quality gate chitchat 短路)
DEFAULT_INTENT: IntentKind = INTENT_CHITCHAT


def classify_intent(message: str) -> IntentKind:
    """轻量意图分类(正则优先,无 LLM 介入)。

    复用 :func:`nexus.backend.middleware.force_tool.classify_intent_lightweight`
    的判定逻辑,把它的字符串返回值映射到 :data:`IntentKind` 字面量:

      - ``"identity"`` → ``"chitchat"``(身份问答不调工具,但要落库供统计)
      - ``"knowledge"`` → ``"knowledge"``
      - ``"task"`` → ``"task"``
      - ``"chitchat"`` → ``"chitchat"``

    Args:
        message: 用户原始消息文本(已 strip)。

    Returns:
        :data:`IntentKind` 字面量,任何异常 / 空消息一律兜底
        :data:`DEFAULT_INTENT`。
    """
    # 延迟 import:force_tool 顶层依赖 langchain AgentMiddleware,避免
    # DB-only 操作(比如查历史 intent 统计)也被迫拉 langchain。
    try:
        from nexus.backend.middleware.force_tool import classify_intent_lightweight
    except ImportError as exc:  # noqa: BLE001
        logger.warning("classify_intent_lightweight 导入失败,兜底 chitchat: %s", exc)
        return DEFAULT_INTENT

    try:
        bucket = classify_intent_lightweight(message or "")
    except Exception as exc:  # noqa: BLE001 - 同步路径,任何意外不影响主流程
        logger.warning("意图分类异常,兜底 chitchat: %s", exc)
        return DEFAULT_INTENT

    # identity 归入 chitchat(身份问答不调工具,但要在 DB 里标记供统计)
    if bucket == "knowledge":
        return INTENT_KNOWLEDGE
    if bucket == "task":
        return INTENT_TASK
    return INTENT_CHITCHAT
