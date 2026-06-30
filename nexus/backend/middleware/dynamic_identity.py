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
from ..models_config import get_active_model_info

logger = logging.getLogger(__name__)


def _build_fact_block(info: dict[str, Any] | None) -> str:
    """根据 ``get_active_model_info()`` 返回值拼 FACT 块字符串。

    与 ``_build_system_prompt`` 里的 FACT 块内容**完全一致**(同一份字符串模板,
    改一处必须改两处)——这样切换前后 LLM 看到的 system prompt 结构不变,
    LLM 训练记忆里如果对"FACT 块结构"有偏好也不会被打破。

    Args:
        info: ``get_active_model_info()`` 返回 dict;``None`` 或缺 ``name`` 走
            降级措辞(``未配置模型``),绝不编造。

    Returns:
        拼好的 FACT 块字符串,末尾带一个空行方便和后面的内容分隔。
    """
    if info and info.get("name"):
        driver_name = info["name"]
        driver_vendor = info.get("vendor", "未知厂商")
    else:
        driver_name = "未配置模型"
        driver_vendor = "未知厂商"

    return (
        f"【FACT · 当前驱动模型 · 运行时实时注入】\n"
        f"- name: `{driver_name}`(每次 LLM 调用前从 `~/.nexus/models.json` 实时读)\n"
        f"- vendor: `{driver_vendor}`(从 api_base URL 自动推断)\n"
        f"- 数据是**活的** —— 切换激活模型后下一轮 LLM 调用会立即反映新值\n"
        f"\n"
        f"**这条 FACT 由 middleware 在每次调用前注入,不是 prompt 模板里的死字符串**。\n"
        f'回答"你用的什么模型"等身份问题时,**直接使用上述 `name` / `vendor` 值**,\n'
        f'不要凭训练记忆瞎答(LLM 训练数据里的"Qwen/Claude/MiniMax-M3"在这里不权威)。\n'
        f"\n"
    )


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

    sm = request.system_message
    sm_content = sm.content if sm is not None and isinstance(sm.content, str) else ""

    if not sm_content:
        # Bug A 防御:deepagents 实际运行时 sm_content 是空字符串,这里重建
        # 完整 system_message = FACT + 静态 product rules。
        # 后续 ``MemoryMiddleware`` 会在本 middleware 之后再追加 AGENTS.md。
        static_prompt = get_system_prompt()
        rebuilt = SystemMessage(content=fact_block + static_prompt)
        new_request = request.override(system_message=rebuilt)
        logger.info(
            "dynamic_identity_middleware: sm_content 为空,已重建 FACT + 静态 product rules "
            "(fact=%d chars, static=%d chars)",
            len(fact_block),
            len(static_prompt),
        )
        return await handler(new_request)

    # 非空分支(deepagents 未来版本可能修复此 bug,或单测场景):保留原始 static prompt
    sm.content = fact_block + sm_content
    return await handler(request)
