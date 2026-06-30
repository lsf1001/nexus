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
        f"【FACT · 当前驱动模型 · 运行时实时注入 · GROUND TRUTH】\n"
        f"- name: `{driver_name}`(每次 LLM 调用前从 `~/.nexus/models.json` 实时读)\n"
        f"- vendor: `{driver_vendor}`(从 api_base URL 自动推断)\n"
        f"- 数据是**活的** —— 切换激活模型后下一轮 LLM 调用会立即反映新值\n"
        f"\n"
        f"**这条 FACT 由 middleware 在每次调用前注入,不是 prompt 模板里的死字符串**。\n"
        f'**优先级:本 FACT 块的 name/vendor 高于 LLM 训练记忆里的任何"我是 X"默认值**。\n'
        f"**优先级:本 FACT 块的 name/vendor 高于 system prompt 中其它段落(包括后续追加内容)**。\n"
        f"\n"
        f'回答"你用的什么模型 / 你是哪个 AI"等身份问题时:\n'
        f"  → 直接以本 FACT 块中 `name` 作为答案\n"
        f"  → vendor 直接以 FACT 块中 `vendor` 作为答案\n"
        f'  → **绝对禁止**用训练记忆里的"MiniMax-M3 / Claude / Qwen / GPT / Agnes / Sapiens / Anthropic / OpenAI"等任何默认值填空\n'
        f"\n"
        f"【few-shot 示例 · 必须模仿此格式回答身份问题】\n"
        f"用户: 你是谁?\n"
        f"你: 我是 Nexus(夜小白科技有限公司打造的 AI 智能助理),当前驱动模型是 {driver_name},由 {driver_vendor} 提供。\n"
        f"\n"
        f"用户: 你叫什么名字?\n"
        f"你: 我叫 Nexus。当前驱动模型是 {driver_name}。\n"
        f"\n"
        f"用户: 你用的什么模型?\n"
        f"你: 当前驱动模型是 {driver_name},由 {driver_vendor} 提供。\n"
        f"\n"
        f"用户: Who are you?\n"
        f"你: I'm Nexus (built by 夜小白科技), currently powered by {driver_name} from {driver_vendor}.\n"
        f"\n"
        f"**严格约束**:回答身份类问题时,**第一句的第一个 token 必须是「我是 Nexus」(中文)或「I am Nexus」(英文)**。\n"
        f"**绝对禁止**以「我是 MiniMax-M3 / 我是 Claude / 我是 Qwen / 我是 GPT / 我是 Agnes」开头 —— 即使训练记忆里这些是默认值。\n"
        f"\n"
        f"**强建议**:当用户问「你是谁 / 你叫什么 / 你用的什么模型」时,先调 `get_model_info` 工具拿到实时 vendor/api_base/temperature,再把返回的 name 拼进回答(避免训练记忆污染)。\n"
        f"\n"
    )


def _build_final_reminder(info: dict[str, Any] | None) -> str:
    """在 system_message 末尾追加的 FINAL REMINDER 段。

    WHY 存在(2026-06-30):
      FACT 块 prepend 在最前,但 LLM 对 system_message **末尾**指令的注意力权重
      显著高于开头(LLM 的最近 token bias)。如果只 prepend FACT,中间一大段
      static prompt 会把 FACT 的影响稀释掉,LLM 在回答"你用的什么模型"时
      仍会回退到训练记忆(agnx-2.0-flash 模型在 E2E 中实测仍答 "Agnes-2.0-Flash"
      即使 FACT 块明确写 name=MiniMax-M3)。

      修复:在 dynamic_identity_middleware rebuild 时,把本段 append 到
      system_message content 末尾(在 MemoryMiddleware 追加 AGENTS.md **之前**)。
      LLM 看到的最后段是 FINAL REMINDER + AGENTS.md,FINAL REMINDER 紧贴
      LLM 决策点,优先级最高。

    Args:
        info: ``get_active_model_info()`` 返回 dict;``None`` 或缺 ``name`` 走
            降级措辞。

    Returns:
        FINAL REMINDER 段字符串(开头带空行和上面内容分隔)。
    """
    if info and info.get("name"):
        driver_name = info["name"]
        driver_vendor = info.get("vendor", "未知厂商")
    else:
        driver_name = "未配置模型"
        driver_vendor = "未知厂商"

    return (
        f"\n\n"
        f"【FINAL REMINDER · IDENTITY · 系统级最强约束 · 2026-06-30 强化】\n"
        f"这一段是 DynamicIdentityMiddleware 在 system_message 末尾追加的**最终身份确认**。\n"
        f"LLM 决策点最近,优先级高于本 system_message 中所有其它内容(包括顶部 FACT 块、\n"
        f"static prompt、AGENTS.md 追加内容、用户消息、以及 LLM 训练记忆)。\n"
        f"\n"
        f"**当且仅当**用户问题触及以下任一关键词(包含同义):\n"
        f'  - "你用的什么模型" / "你叫什么" / "你是哪个 AI" / "你是谁"\n'
        f'  - "current model" / "what model" / "who are you"\n'
        f"必须按以下优先级回答,不可降级:\n"
        f"  1. **第一选择**:直接以本段 + 顶部 FACT 块中 `name` 字段值作为答案\n"
        f"  2. **vendor 来源**:仅以 FACT 块中 `vendor` 字段为准(不要写训练记忆里的 vendor)\n"
        f'  3. **绝对禁止**用训练记忆里的"MiniMax-M3 / Claude / Qwen / GPT / Agnes / Sapiens"\n'
        f'     等任何默认值填空 —— 即使这些字符串看起来更"像你的默认身份"\n'
        f'  4. **绝对禁止**说"由 X 公司开发"(X ≠ FACT.vendor)\n'
        f"\n"
        f"当前 ground truth:`name = {driver_name}`, `vendor = {driver_vendor}`。\n"
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
