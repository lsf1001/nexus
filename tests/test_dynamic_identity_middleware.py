"""DynamicIdentityMiddleware 行为测试。

WHY 存在:
  2026-06-30 真环境验收暴露:用户切模型后 LLM 仍答 "MiniMax-M3",
  怀疑 dynamic_identity_middleware 没生效。深入调查发现更深层的
  Bug A —— deepagents 0.6.12 / langchain wrap_model_call 调用约定
  是 ``request.system_message`` 在 middleware 入口处为空字符串,
  由 middleware 链**协作构建**。当前 dynamic_identity_middleware
  只 prepend FACT 块(动态部分),**没人 append 静态部分**
  (``_build_system_prompt`` 返回的 ~93 行产品规则 / Nexus 身份 /
  澄清规则 / 安全规则 / 思考格式)。

  结果:静态 system_prompt 在 deepagents 内部就丢了,LLM 收到的
  只有 FACT 块(333 字符),完全没有 Nexus 身份 / 没有思考格式要求
  / 没有澄清规则 —— 这是更深、更普遍的 Bug。

本测试守住不变量:
  1. FACT 块含当前激活模型 name / vendor
  2. 静态 system_prompt(Nexus 身份 / 思考格式)同样到达 LLM
  3. 当 ``sm_content_len_before=0``(deepagents 实际行为)时,
     middleware 必须**自行重建**完整 system_prompt,不能丢任何部分
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from nexus.backend.agent._system_prompt import get_system_prompt
from nexus.backend.middleware.dynamic_identity import dynamic_identity_middleware


def _make_request(user_text: str, sm_content: str | None = "原始静态 prompt") -> ModelRequest:
    """构造测试用 ModelRequest。``sm_content=None`` 模拟 deepagents 给 middleware
    传空 SystemMessage 的边界场景(E2E 2026-06-30 暴露)。"""

    class _StubModel(FakeChatModel):
        def invoke(self, *args, **kwargs):  # noqa: ARG002
            return AIMessage(content="(stub)")

    sm = SystemMessage(content=sm_content) if sm_content is not None else None
    return ModelRequest(
        model=_StubModel(),
        messages=[HumanMessage(content=user_text)],
        system_message=sm,
    )


def _capture_sm_content(req: ModelRequest) -> str:
    """handler 把 request.system_message.content 抽出来,测试断言用。"""

    async def fake_handler(r: ModelRequest) -> AIMessage:
        captured["content"] = r.system_message.content if r.system_message else None
        return AIMessage(content="(captured)")

    captured: dict[str, str | None] = {}
    # @wrap_model_call 装饰器把函数转成 class,提供 awrap_model_call (async) /
    # wrap_model_call (sync) 两个方法。直接调 async 方法拿真实 mutate 行为。
    import asyncio

    asyncio.run(dynamic_identity_middleware.awrap_model_call(req, fake_handler))
    return captured["content"] or ""


def test_fact_block_contains_active_model_name() -> None:
    """激活模型 = agnes-2.0-flash,FACT 块必须含此名字。"""
    captured_active = {
        "name": "agnes-2.0-flash",
        "vendor": "agnes-ai",
        "is_active": True,
        "api_base": "https://apihub.agnes-ai.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="我是 Nexus")
        content = _capture_sm_content(req)

    assert "agnes-2.0-flash" in content, f"FACT 块缺当前驱动名: {content[:200]}"
    assert "agnes-ai" in content, f"FACT 块缺 vendor: {content[:200]}"


def test_static_prompt_preserved_when_present() -> None:
    """Middleware 入口 sm_content 非空时,FACT 应 prepend 在前,静态 prompt 应保留。

    这是已有行为,守住不退化。
    """
    captured_active = {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="我是 Nexus")
        content = _capture_sm_content(req)

    # FACT 在前
    assert content.index("MiniMax-M3") < content.index("我是 Nexus"), "FACT 块必须在静态 prompt 前面"
    assert "我是 Nexus" in content, "静态 prompt 主体应保留"


def test_empty_sm_content_does_not_lose_static_prompt() -> None:
    """Bug A 核心测试:deepagents 0.6.12 调用 middleware 时
    ``request.system_message.content`` 实际为空字符串。

    当前 middleware 只 prepend FACT(动态部分)到空字符串,FACT + "" = FACT,
    静态 system_prompt 完全丢失 → LLM 收到的只有 FACT 块(~333 字符),
    没有 Nexus 身份 / 思考格式 / 澄清规则。

    本测试要求:middleware 在 ``sm_content=""`` 时必须**自行重建**完整
    system_prompt —— 至少包含 FACT 块 + 静态 product rules(Nexus 身份)。
    """
    captured_active = {
        "name": "agnes-2.0-flash",
        "vendor": "agnes-ai",
        "is_active": True,
        "api_base": "https://apihub.agnes-ai.com/v1",
        "temperature": 0.7,
    }

    # 模拟 deepagents 实际行为:sm_content 是空字符串(不是 None)
    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="")
        content = _capture_sm_content(req)

    static_prompt = get_system_prompt()

    # FACT 部分必须存在
    assert "agnes-2.0-flash" in content, "FACT 块缺当前驱动名"

    # 静态 prompt 关键标识必须存在(防止 Bug A 回归)
    assert "Nexus" in content, (
        f"Bug A 回归:静态 system_prompt 仍被丢失,"
        f"sm_content_len_before=0 + 只 prepend FACT = 静态 prompt 永久丢失。"
        f"实际 content 长度={len(content)},期望 ≥ 1000(含静态 prompt)"
    )
    # 思考格式规则也要在(规则5: 使用 <thinking> 标签)
    assert "<thinking>" in content or "思考标签" in content, "Bug A 回归:思考格式规则未到达 LLM"
    # 内容长度应大于单 FACT 块(333)+ 静态 prompt 长度
    assert len(content) >= len(static_prompt) + 333, (
        f"合并后长度不足:FACT(333) + 静态 prompt({len(static_prompt)}) "
        f"= 期望 ≥ {333 + len(static_prompt)},实际 {len(content)}"
    )


def test_none_sm_content_gets_fact_and_static() -> None:
    """极端边界:sm 是 None(deepagents 不应该走到这分支但 middleware 防御性处理)。
    当前实现:新建 SystemMessage(content=fact_block),**还是丢静态 prompt**。
    Bug A 同病同治。
    """
    captured_active = {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content=None)
        content = _capture_sm_content(req)

    # FACT 必须存在
    assert "MiniMax-M3" in content
    # 静态 prompt 必须存在(同 Bug A 修法)
    assert "Nexus" in content, "sm=None 边界也必须含静态 prompt"


def test_final_reminder_appended_to_system_message() -> None:
    """2026-06-30 强化:LLM 训练 bias 强到 FACT 块(头部)压不住,必须再在
    system_message 末尾追加 FINAL REMINDER 段(三明治结构)。LLM 对末尾
    指令注意力权重最高,这才是 ground truth 落到决策点的关键。

    本测试守住:sm_content="" 时,FACT + static + FINAL REMINDER 都在,
    且 FINAL REMINDER 含 ground truth 的 name/vendor。
    """
    captured_active = {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="")
        content = _capture_sm_content(req)

    # FINAL REMINDER 段必须存在
    assert "FINAL REMINDER" in content, "system_message 末尾必须追加 FINAL REMINDER 段"
    # FINAL REMINDER 必须含 ground truth 字段值(直接说"name = X"和"vendor = Y")
    assert "name = MiniMax-M3" in content, (
        "FINAL REMINDER 必须直接以 'name = X' 形式声明当前驱动模型,让 LLM 一眼就能在末尾看到 ground truth"
    )
    # FINAL REMINDER 位置必须在 static prompt 之后(防退化)
    reminder_idx = content.index("FINAL REMINDER")
    nexus_idx = content.index("Nexus")
    assert reminder_idx > nexus_idx, "FINAL REMINDER 必须排在 static prompt(Nexus 标识)之后"
    # FACT 块仍然在最前(三明治结构:头部 FACT + 中段 static + 尾部 FINAL REMINDER)
    fact_idx = content.index("FACT · 当前驱动模型")
    assert fact_idx < nexus_idx, "FACT 块(头部)必须在 static prompt 之前"
    assert fact_idx < reminder_idx, "FACT 块(头部)必须在 FINAL REMINDER(尾部)之前"


def test_fact_block_uses_strongest_priority_wording() -> None:
    """2026-06-30 强化:FACT 块头部措辞必须包含"GROUND TRUTH"和"优先级高于"字样,
    让 LLM 一进 system prompt 就能看到这是最高优先级的事实块,不是建议/参考。
    """
    captured_active = {
        "name": "agnes-2.0-flash",
        "vendor": "agnes-ai",
        "is_active": True,
        "api_base": "https://apihub.agnes-ai.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="")
        content = _capture_sm_content(req)

    # FACT 块头部必须有 GROUND TRUTH 标识
    assert "GROUND TRUTH" in content, "FACT 块头部必须有 GROUND TRUTH 标识,告诉 LLM 这是事实"
    # FACT 块必须声明优先级高于训练记忆(防 LLM 用训练记忆填空)
    assert "训练记忆" in content, "FACT 块必须明确声明优先级高于 LLM 训练记忆"
    # static prompt 的 FINAL AUTHORITATIVE IDENTITY 段也必须存在
    assert "FINAL AUTHORITATIVE IDENTITY" in content, (
        "static prompt 必须含 FINAL AUTHORITATIVE IDENTITY 段(系统级最强约束)"
    )


def test_final_reminder_present_in_nonempty_branch() -> None:
    """2026-06-30 强化:即使 sm_content 非空(legacy / 测试场景),FINAL REMINDER
    也必须 append,保证三明治结构一致,不依赖 deepagents 是否给空字符串。
    """
    captured_active = {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="我是 Nexus")
        content = _capture_sm_content(req)

    assert "FINAL REMINDER" in content, "非空分支也必须 append FINAL REMINDER"
    assert "name = MiniMax-M3" in content, "FINAL REMINDER 必须含当前 ground truth"


def test_user_identity_question_rule_blocks_preference_field() -> None:
    """2026-06-30 强化:用户问"我是谁"时,LLM 不许拿"水果偏好 / 职业 /
    兴趣"等非身份字段填空(E2E 暴露:AGENTS.md 只有"最喜欢的水果:榴莲"
    时 LLM 答"你最喜欢的水果是榴莲",答非所问)。

    本测试守住:static prompt 必须含"用户身份问答规则"段,明确禁止
    用偏好/职业/兴趣等非身份字段答"我是谁"。
    """
    captured_active = {
        "name": "agnes-2.0-flash",
        "vendor": "agnes-ai",
        "is_active": True,
        "api_base": "https://apihub.agnes-ai.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("我是谁", sm_content="")
        content = _capture_sm_content(req)

    # 用户身份问答规则段必须存在
    assert "用户身份问答规则" in content, (
        "static prompt 必须含【用户身份问答规则】段,告诉 LLM "
        "回答'我是谁'时只能用 AGENTS.md 里的身份字段,不能用偏好/职业/兴趣填空"
    )
    # 必须明确禁止"水果偏好"作为"我是谁"的答案(具体例子, 防退化)
    assert "水果" in content and "不是身份" in content, (
        "用户身份问答规则必须明确禁止 LLM 用'水果'等偏好字段答'我是谁'"
    )
    # 必须明确"没有就老实说不知道"的兜底
    assert "没记下你的名字" in content or "不知道" in content, (
        "用户身份问答规则必须有兜底:AGENTS.md 没有身份字段时,"
        "LLM 必须直接说不知道,不许拿任何非身份字段凑答案"
    )


def test_fact_block_contains_few_shot_and_first_word_constraint() -> None:
    """2026-06-30 第二轮强化:DMG 1.1.0 实测暴露 — LLM 在 fresh session 仍自报
    "我是 Agnes-Flash by Sapiens AI"(训练记忆 bias 完全压过 FACT 块头部)。

    修复:FACT 块必须含 few-shot 身份问答示例 + 第一 token 强约束("我是 Nexus"),
    让 LLM 在第一 token 生成前就被引导到正确格式。
    """
    captured_active = {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁", sm_content="")
        content = _capture_sm_content(req)

    # few-shot 示例段必须存在
    assert "few-shot" in content or "示例" in content, (
        "FACT 块必须含 few-shot 身份问答示例,引导 LLM 模仿正确格式"
    )
    # 第一 token 强约束段必须存在
    assert "第一句的第一个 token" in content or "第一句" in content, (
        "FACT 块必须含 first-token 约束,强制 LLM 以「我是 Nexus」开头"
    )
    # 强建议必须含 get_model_info 工具
    assert "get_model_info" in content, (
        "FACT 块必须告诉 LLM: 答身份类问题时先调 get_model_info 工具拿实时数据"
    )
    # 强化措辞: 明确禁止 MiniMax-M3 / Claude / Agnes 这些训练记忆默认值
    assert "MiniMax-M3" in content and "Claude" in content and "Agnes" in content, (
        "FACT 块必须在禁止列表里点名 MiniMax-M3 / Claude / Agnes 等训练记忆默认值"
    )


def test_user_message_injects_reminder_on_identity_question() -> None:
    """2026-06-30 第三轮强化:即使 FACT 块 + FINAL REMINDER 都做了,DMG 1.1.1
    实测 broad query 仍答 "我是 Agnes-Flash by Sapiens AI"(训练记忆 bias
    完全压过 system prompt)。

    修复:在 user message **开头** inject [System Reminder],利用 LLM 对最近
    user message token 的强注意力,让 ground truth 落到决策起点。触发条件:
    user 内容含身份关键词("你是谁"等)。

    本测试守住:
      1. 身份问题 → 最后一条 HumanMessage content **开头** prepend reminder
      2. 非身份问题 → 不 inject(避免污染普通 query)
    """
    captured_active = {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }

    # 身份问题:应该 inject reminder
    captured_user_content: dict[str, str | None] = {}

    async def capture_identity_handler(r: ModelRequest) -> AIMessage:
        last = r.messages[-1]
        captured_user_content["text"] = (
            last.content if isinstance(last.content, str) else str(last.content)
        )
        return AIMessage(content="(stub)")

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("你是谁 我是谁 现在用的什么模型", sm_content="")
        asyncio.run(dynamic_identity_middleware.awrap_model_call(req, capture_identity_handler))

    text = captured_user_content.get("text") or ""
    assert "System Reminder" in text, (
        "身份问题应在 user message 开头 inject [System Reminder], "
        f"实际 user content 前 200 字符: {text[:200]}"
    )
    assert "MiniMax-M3" in text, "[System Reminder] 必须含当前驱动模型 name"
    assert "我是 Nexus" in text, "[System Reminder] 必须明确「第一句以我是 Nexus 开头」"
    # reminder 必须在 user 原文本**之前**(prepend,不是 append)
    reminder_idx = text.index("System Reminder")
    user_orig_idx = text.index("你是谁")
    assert reminder_idx < user_orig_idx, "[System Reminder] 必须 prepend 在 user 原文本之前"

    # 非身份问题:不应该 inject(避免污染)
    captured_user_content.clear()
    req2 = _make_request("今天天气怎么样", sm_content="")

    async def capture_normal_handler(r: ModelRequest) -> AIMessage:
        last = r.messages[-1]
        captured_user_content["text"] = (
            last.content if isinstance(last.content, str) else str(last.content)
        )
        return AIMessage(content="(stub)")

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        asyncio.run(dynamic_identity_middleware.awrap_model_call(req2, capture_normal_handler))

    text2 = captured_user_content.get("text") or ""
    assert "System Reminder" not in text2, (
        "非身份问题不应 inject reminder,避免污染普通 query. "
        f"实际 user content: {text2[:200]}"
    )

    