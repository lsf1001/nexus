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

契约:
  - 输入 ``request.system_message.content`` 必须是 ``str``(deepagents / langgraph
    ``create_agent`` 走 ``system_prompt: str | SystemMessage`` 路径,本 middleware
    只处理 str 分支,其他情况 noop)。
  - ``get_active_model_info()`` 是 cheap 操作(单次 ``json.loads`` 6KB 文件) →
    每次 LLM 调用读一次完全可接受(LLM 调用本身几十毫秒到几秒,加 1ms 文件
    读可忽略)。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelRequest, ModelResponse

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
      - 如果 ``request.system_message`` 为 ``None``(理论上 create_agent
        必须传 system_prompt,这里只是防御),新建一个空 SystemMessage 再 prepend。
      - mutate 的是 ``request.system_message.content``(in-place 改 str),
        然后 ``handler(request)`` 透传 —— handler 拿到的就是带最新 FACT 的版本。
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
    if sm is None:
        # 防御性:create_agent 不应该走到这分支(传了 system_prompt)。
        # 如果走到,造一个空 SystemMessage 注入 FACT,保证 LLM 至少知道当前驱动。
        from langchain_core.messages import SystemMessage

        request.system_message = SystemMessage(content=fact_block)
        logger.warning("dynamic_identity_middleware: request.system_message 为 None,已新建空 SystemMessage")
    else:
        # mutate content:prepend FACT,后跟原始 system_prompt
        existing = sm.content if isinstance(sm.content, str) else str(sm.content)
        sm.content = fact_block + existing

    return await handler(request)
