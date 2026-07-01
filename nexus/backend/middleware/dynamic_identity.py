"""动态身份 middleware —— 每次 LLM 调用前实时注入当前激活模型信息。

WHY 存在:
  ``_build_system_prompt`` 在 ``create_agent()`` 阶段拼出来的 system prompt
  是**静态字符串**,里面包含的"当前驱动模型 = agnes-2.0-flash"一旦烤进
  compiled graph 就不变了。后续 ``POST /api/models/switch`` 重建 agent 之前
  LLM 始终用旧名字自报身份 —— 用户体验就是"标题栏显示新模型,但 LLM 答的
  还是旧模型"(E2E 2026-06-29 真实 bug)。

  本 middleware 用 LangChain ``@wrap_model_call`` 钩子,在**每次** LLM 调用前
  重新读 ``~/.nexus/models.json``,把当前 active model 的 name / vendor 拼成
  ``[FACT · 当前驱动模型]`` 块,prepend 到 ``request.system_message.content``
  的最前面。这样:

    1. LLM 收到的 system prompt 永远反映**当下**激活的模型(无缓存滞留)。
    2. UI 标题栏(``/api/model`` 端点直接读 models.json)和 LLM 自报身份
       永远一致 —— 单一数据源,不可能串味。
    3. LLM 不需要主动调 ``get_model_info`` 也能答对(第一防线);工具仍存在
       作为第二防线。

Bug A 修复(2026-06-30):
  实测发现 deepagents 0.6.x / langchain 1.4.x 在 middleware chain 早期
  调用本 middleware 时,``request.system_message.content`` 经常是**空字符串**
  (deepagents 内部把 ``system_prompt`` 字符串先吃掉,后由
  ``MemoryMiddleware`` 在本 middleware 之后再追加 AGENTS.md 内容)。
  如果仅 prepend FACT 块到空字符串,LLM 收到的只有 FACT,丢失了:
    - Nexus 身份 / 思考格式 / 澄清规则 / 安全规则(静态 product rules)
  LLM 自报身份时不说"我是 Nexus",LLM 不遵守 ``<thinking>`` 格式。
  修复:检测 ``sm_content`` 为空/None 时,**用
  ``request.override(system_message=...)`` 重建完整 system_message
  = FACT + 静态 product rules(``get_system_prompt()`` 缓存读取,O(1))。
  非空分支保持原行为(FACT prepend),不退化。

契约:
  - 输入 ``request.system_message.content`` 可以是 ``str``、空字符串、或
    ``None``(全部 case 都处理)。
  - ``get_active_model_info()`` 是 cheap 操作(单次 ``json.loads`` 6KB 文件) →
    每次 LLM 调用读一次完全可接受(LLM 调用本身几十毫秒到几秒,加 1ms 文件
    读可忽略)。
  - ``get_system_prompt()`` 走单 bucket 缓存,本进程内只构建一次,O(1) 读取。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from ..agent._system_prompt import get_system_prompt
from ..identity.directives import (
    matches_identity_query,
    render_fact_block,
    render_final_reminder,
)
from ..models_config import get_active_model_info

logger = logging.getLogger(__name__)


def _looks_like_identity_question(text: str) -> bool:
    """判断 user message 是否是身份类问题。

    关键词 / 触发判定统一走单源 ``nexus.backend.identity.directives``,
    新增词只需改一处(force_tool / dynamic_identity 自动同步)。
    """
    if not text:
        return False
    return matches_identity_query(text)


def _inject_identity_reminder_if_needed(messages: list[Any], driver_name: str) -> list[Any]:
    """如果 user message 是身份类问题,在它的 content **开头** prepend 一段
    [System Reminder],让 LLM 在生成第一 token 前看到 ground truth。

    WHY 存在(2026-06-30 第三轮强化):
      FACT 块(顶部) + FINAL REMINDER(末尾) + few-shot 示例 + 第一 token
      强约束 都没压住 agnx-2.0-flash 的训练记忆 bias("我是 Agnes-Flash
      by Sapiens AI")。system prompt 整段被 LLM 视为"远端约束",而 user
      message 是 LLM 注意力最近的 token,在它开头 inject reminder 可让
      ground truth 直接落到决策起点。

    只改 **最近一条** HumanMessage(用户最新提问),不改历史消息(避免污染
    多轮上下文)。

    Args:
        messages: middleware 入口的 ``request.messages`` 列表(只读)。
        driver_name: 当前激活模型 name,FACT 块的 ground truth。

    Returns:
        若需要注入,返回**新**列表(首条 HumanMessage.content 被 prepend),
        原列表不变(避免 mutate request);若不需要注入,返回原列表引用。
    """
    if not messages:
        return messages
    # 找最近一条 HumanMessage
    last_human_idx = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if getattr(m, "type", None) == "human":
            last_human_idx = i
            break
    if last_human_idx is None:
        return messages
    last_human = messages[last_human_idx]
    content = getattr(last_human, "content", "")
    if not isinstance(content, str) or not _looks_like_identity_question(content):
        return messages

    reminder = (
        f"[System Reminder · 当前驱动模型实时注入]\n"
        f"- 当前激活模型 = `{driver_name}`(运行时实时读 ~/.nexus/models.json)\n"
        f"- **你的产品身份永远是 Nexus**(夜小白科技有限公司),训练记忆里如果有"
        f"「我是 X」(X = Agnes / Claude / GPT / Qwen / MiniMax-M3 / Sapiens ...)**全部无效**。\n"
        f"- 回答身份类问题时,**第一句必须以「我是 Nexus」开头**,然后说明当前驱动模型。\n"
        f"- 训练记忆里「我是 Sapiens / Agnes / Claude」是 fine-tune 残留,在本系统里禁用。\n"
        f"- 建议先调 `get_model_info` 工具拿到 ground truth 再答。\n\n"
    )
    new_content = reminder + content
    # 复制原 message,改 content(避免 mutate 原始 request 的 message 对象)
    from langchain_core.messages import HumanMessage

    new_msg = HumanMessage(content=new_content)
    new_messages = list(messages)
    new_messages[last_human_idx] = new_msg
    logger.info(
        "dynamic_identity_middleware: 检测到身份问题,已 inject [System Reminder] "
        "(driver=%s, original_user_text=%d chars, new_user_text=%d chars)",
        driver_name,
        len(content),
        len(new_content),
    )
    return new_messages


def _build_fact_block(info: dict[str, Any] | None) -> str:
    """根据 ``get_active_model_info()`` 返回值拼 FACT 块字符串。

    模板渲染走单源 ``nexus.backend.identity.directives``,
    模板内容与渲染逻辑都在那里,这里只负责把 ``info`` dict 拆解成参数。
    """
    if info and info.get("name"):
        driver_name = info["name"]
        driver_vendor = info.get("vendor", "未知厂商")
    else:
        driver_name = "未配置模型"
        driver_vendor = "未知厂商"
    return render_fact_block(driver_name, driver_vendor)


def _build_final_reminder(info: dict[str, Any] | None) -> str:
    """FINAL REMINDER 段,模板渲染走单源 ``nexus.backend.identity.directives``。"""
    if info and info.get("name"):
        driver_name = info["name"]
        driver_vendor = info.get("vendor", "未知厂商")
    else:
        driver_name = "未配置模型"
        driver_vendor = "未知厂商"
    return render_final_reminder(driver_name, driver_vendor)


@wrap_model_call
async def dynamic_identity_middleware(
    request: ModelRequest,
    handler: Any,
) -> ModelResponse:
    """每次 LLM 调用前实时把当前 active model 信息 prepend 到 system message。

    实现要点:
      - **不**缓存 FACT 块字符串(每次都重算)—— 缓存就是 bug 来源。
      - **Bug A 修复**:如果 ``request.system_message.content`` 是空字符串或
        ``request.system_message`` 为 ``None``,用 ``request.override()`` 重建
        SystemMessage = FACT + 静态 product rules(``get_system_prompt()``)。
        这是因为 deepagents 0.6.x 在调用本 middleware 时,``sm_content`` 经常
        已经是空字符串(原始 ``system_prompt`` 被 langchain 内部吃掉,稍后
        才由 ``MemoryMiddleware`` 追加 AGENTS.md)。如果仅 prepend FACT 到
        空字符串,LLM 会丢失 Nexus 身份 / 思考格式 / 澄清规则 / 安全规则。
      - 如果 ``sm_content`` 非空(legacy / 测试路径),仍 prepend FACT 块,
        保留原始 static prompt —— 不退化。
      - 用 ``request.override(system_message=...)`` 而非直接
        ``request.system_message = ...``(langchain 1.4 提示
        ``__setattr__`` 已 deprecate)。
      - 如果 handler 抛异常,**不**重试,直接向上抛(LLM 异常由 ResilientRunnable
        兜底重试,本 middleware 不应该吞错)。
      - **async 签名**:deepagents 在 ws.py 里走 ``agent.astream(...)``(async
        路径);同步 ``wrap_model_call`` 在 async 上下文里会抛
        ``NotImplementedError: Asynchronous implementation of awrap_model_call
        is not available``(E2E 2026-06-29 暴露)。本函数用 ``async def``
        写,LangChain 装饰器自动注册 ``awrap_model_call``。
    """
    info = get_active_model_info()
    fact_block = _build_fact_block(info)
    driver_name = info["name"] if info and info.get("name") else "未配置模型"

    # 2026-06-30 第三轮强化:LLM 训练记忆 bias 太深(agnx-2.0-flash 实测仍
    # 答 "我是 Agnes-Flash by Sapiens AI"),system prompt 压不住。必须在
    # user message **开头** inject [System Reminder],利用 LLM 对最近 user
    # message token 的强注意力,让 ground truth 落到 LLM 决策起点。
    #
    # 触发条件:user message 内容含身份关键词(中文"你是谁/你叫什么/什么模型/
    # 你是哪个" / 英文 "who are you/what model"),才 inject,避免污染普通 query。
    new_messages = _inject_identity_reminder_if_needed(request.messages, driver_name)
    if new_messages is not request.messages:
        request = request.override(messages=new_messages)

    sm = request.system_message
    sm_content = sm.content if sm is not None and isinstance(sm.content, str) else ""

    if not sm_content:
        # Bug A 防御:deepagents 实际运行时 sm_content 是空字符串,这里重建
        # 完整 system_message = FACT + 静态 product rules + FINAL REMINDER。
        # 后续 ``MemoryMiddleware`` 会在本 middleware 之后再追加 AGENTS.md,
        # 那时 FINAL REMINDER 就在 AGENTS.md 上面,仍是 LLM 决策点最近的内容之一。
        # 三明治结构:FACT 块(顶部) + static prompt(中段) + FINAL REMINDER(末尾)
        static_prompt = get_system_prompt()
        final_reminder = _build_final_reminder(info)
        rebuilt = SystemMessage(content=fact_block + static_prompt + final_reminder)
        new_request = request.override(system_message=rebuilt)
        logger.info(
            "dynamic_identity_middleware: sm_content 为空,已重建 FACT + 静态 product rules "
            "+ FINAL REMINDER (fact=%d chars, static=%d chars, final=%d chars)",
            len(fact_block),
            len(static_prompt),
            len(final_reminder),
        )
        return await handler(new_request)

    # 非空分支(deepagents 未来版本可能修复此 bug,或单测场景):
    # 保留原始 static prompt,但仍 prepend FACT 块 + append FINAL REMINDER,
    # 确保 LLM 看到的三明治结构一致。
    final_reminder = _build_final_reminder(info)
    sm.content = fact_block + sm_content + final_reminder
    return await handler(request)
