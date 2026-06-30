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
