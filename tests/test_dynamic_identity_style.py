"""DynamicIdentityMiddleware style 维度透传测试(Round 6.1 bug fix 回归)。

WHY 存在:
  Round 6.1 Task 6/8 实施后,LLM 永远按 default 风格回复(选了"专业"
  也不生效)。根因:``DynamicIdentityMiddleware`` 在 ``wrap_model_call``
  阶段 ``request.system_message.content`` 是空字符串(deepagents 0.7.4
  把 system_prompt 在内部吃掉了),走 Bug A 防御重建 SystemMessage 时
  调 ``get_system_prompt()`` 无参,默认 style='default',结果把 agent
  在 create_agent 阶段按 ``style='professional'`` 拼进 messages[0]
  的【回复风格 · 专业】段覆盖掉。

修复方案:在 ``_agent_builder.create_agent`` 把 style 写到
``llm._nexus_style``,middleware 入口读 ``request.model._nexus_style``,
重建时透传给 ``get_system_prompt(style=...)``。

本测试守住:
  1. ``_nexus_style='professional'`` → LLM 真收到含【专业】段 prompt
  2. ``_nexus_style='concise'`` → LLM 真收到含【简洁】段 prompt
  3. ``_nexus_style='default'`` 或未设 → LLM 收到无风格段 prompt(防 Bug A 退化)
  4. 切换风格('default' → 'professional' → 'concise')分别独立生效,
     互不污染(防 cache bucket 错乱)

设计参考:
  - ``test_dynamic_identity_middleware.py`` 提供 ``_make_request`` /
    ``_capture_sm_content`` 模式,本测试沿用同套路。
"""

from __future__ import annotations

from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from nexus.backend.agent._system_prompt import (
    _CACHED_PROMPT,
    get_system_prompt,
    reload_system_prompt,
)
from nexus.backend.middleware.dynamic_identity import dynamic_identity_middleware


def _make_request(
    user_text: str,
    sm_content: str | None = "",
    style: str | None = None,
) -> ModelRequest:
    """构造测试用 ModelRequest,模拟 deepagents 0.7.4 实际行为。

    Args:
        user_text: 用户消息内容。
        sm_content: middleware 入口处的 system_message.content。
            传 ``""`` 模拟 deepagents 真实运行时行为(空字符串,
            Bug A 防御分支)。
        style: 写到 ``llm._nexus_style`` 的风格值,模拟 create_agent
            阶段注入。``None`` 表示不设属性(走 fallback 'default')。

    Returns:
        配置好的 ModelRequest 实例。
    """

    class _StubModel(FakeChatModel):
        def invoke(self, *args, **kwargs):  # noqa: ARG002
            return AIMessage(content="(stub)")

    model = _StubModel()
    if style is not None:
        model._nexus_style = style  # type: ignore[attr-defined]
    sm = SystemMessage(content=sm_content) if sm_content is not None else None
    return ModelRequest(
        model=model,
        messages=[HumanMessage(content=user_text)],
        system_message=sm,
    )


def _capture_sm_content(req: ModelRequest) -> str:
    """handler 把 request.system_message.content 抽出来,测试断言用。"""
    captured: dict[str, str | None] = {}

    async def fake_handler(r: ModelRequest) -> AIMessage:
        captured["content"] = r.system_message.content if r.system_message else None
        return AIMessage(content="(captured)")

    import asyncio

    asyncio.run(dynamic_identity_middleware.awrap_model_call(req, fake_handler))
    return captured["content"] or ""


def _make_captured_active_model() -> dict[str, str | float]:
    """测试用激活模型信息。"""
    return {
        "name": "MiniMax-M3",
        "vendor": "MiniMax",
        "is_active": True,
        "api_base": "https://api.minimaxi.com/v1",
        "temperature": 0.7,
    }


def test_professional_style_preserved_in_rebuilt_prompt() -> None:
    """Round 6.1 bug fix 核心回归。

    当 ``llm._nexus_style='professional'`` 时,middleware 重建的
    SystemMessage 必须包含【回复风格 · 专业】段 —— 否则 LLM 永远按
    default 风格回复。
    """
    reload_system_prompt()  # 清缓存避免上轮测试污染
    captured_active = _make_captured_active_model()

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("测试", sm_content="", style="professional")
        content = _capture_sm_content(req)

    assert "回复风格 · 专业" in content, (
        f"Round 6.1 bug 回归: middleware 重建 SystemMessage 时丢失"
        f"style='professional' 指令段。实际 content 前 500 字符: {content[:500]}"
    )
    # 专业段的核心特征: 用词严谨、依据、结构化输出
    assert "用词严谨" in content or "精准" in content, "【回复风格 · 专业】段关键约束(用词严谨/精准)未到达 LLM"


def test_concise_style_preserved_in_rebuilt_prompt() -> None:
    """``_nexus_style='concise'`` 时,【回复风格 · 简洁】段必须保留。"""
    reload_system_prompt()
    captured_active = _make_captured_active_model()

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("测试", sm_content="", style="concise")
        content = _capture_sm_content(req)

    assert "回复风格 · 简洁" in content, (
        f"middleware 重建 SystemMessage 时丢失 style='concise' 指令段。实际 content 前 500 字符: {content[:500]}"
    )
    # 简洁段的核心特征: 不寒暄、不铺陈、不复述问题
    assert "不寒暄" in content or "不铺陈" in content, "【回复风格 · 简洁】段关键约束(不寒暄/不铺陈)未到达 LLM"


def test_default_style_omits_directive() -> None:
    """``_nexus_style='default'`` 时,middleware 不应附加风格段(防 Bug A 退化)。

    这是 Bug A 防御:即使 style='default',也得有完整 Nexus 身份 / 思考
    格式 / 澄清规则 + FACT 块 + FINAL REMINDER,只是不带【回复风格 · *】段。
    """
    reload_system_prompt()
    captured_active = _make_captured_active_model()

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("测试", sm_content="", style="default")
        content = _capture_sm_content(req)

    # 默认风格不应含任何【回复风格 · *】指令段
    assert "回复风格 ·" not in content, f"style='default' 时不应附加任何风格段,实际 content: {content[:500]}"
    # Bug A 防御仍须保留(核心 Nexus 身份 / FACT 块)
    assert "Nexus" in content, "Bug A 防御: 默认风格也必须含 Nexus 身份段"
    assert "MiniMax-M3" in content, "FACT 块必须保留(默认风格也含当前激活模型)"


def test_no_nexus_style_attribute_defaults_to_default() -> None:
    """未设 ``_nexus_style`` 属性时(向后兼容),middleware 走 default 风格。

    WHY 兼容:存量测试 / 第三方调用方可能用裸 BaseChatModel(无 _nexus_style),
    middleware 须用 ``getattr(..., "default")`` 兜底。
    """
    reload_system_prompt()
    captured_active = _make_captured_active_model()

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        # style=None 表示不设 _nexus_style 属性
        req = _make_request("测试", sm_content="", style=None)
        content = _capture_sm_content(req)

    assert "回复风格 ·" not in content, (
        f"未设 _nexus_style 时应走默认风格,不应附加任何风格段。实际 content: {content[:500]}"
    )
    # 静态 prompt 仍须含(Nexus 身份 + 思考格式)
    assert "Nexus" in content


def test_style_switches_use_independent_cache_buckets() -> None:
    """切换风格('professional' → 'concise')各自命中独立 cache bucket。

    WHY:防 Round 6.1 修后引入新 bug — 同一个 _CACHED_PROMPT entry
    被多次写覆盖,导致风格段串味。
    """
    reload_system_prompt()
    p_professional = get_system_prompt(style="professional")
    p_concise = get_system_prompt(style="concise")

    # 两次不同 style 调,cache 必须有两份独立 entry
    assert len(_CACHED_PROMPT) >= 2
    assert "回复风格 · 专业" in p_professional
    assert "回复风格 · 简洁" in p_concise
    assert p_professional != p_concise


def test_rebuilt_prompt_structure_sandwich_intact() -> None:
    """Round 6.1 修复后,style=professional 重建的三明治结构仍正确:

    FACT(顶) → FACT_CHECK(顶 2) → static(含【专业】段,中段)
            → FINAL REMINDER(末尾,含 ground truth)
    """
    reload_system_prompt()
    captured_active = _make_captured_active_model()

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        req = _make_request("测试", sm_content="", style="professional")
        content = _capture_sm_content(req)

    # FACT 块在头部
    fact_idx = content.index("FACT · 当前驱动模型")
    # Nexus 身份(中段)
    nexus_idx = content.index("Nexus")
    # FINAL REMINDER 在末尾
    reminder_idx = content.index("FINAL REMINDER")
    # 【专业】段在 Nexus 之后、FINAL REMINDER 之前(中段靠后)
    style_idx = content.index("回复风格 · 专业")

    assert fact_idx < nexus_idx, "FACT 块必须在 static prompt 之前"
    assert fact_idx < style_idx, "FACT 块必须在【专业】段之前"
    assert style_idx < reminder_idx, "【专业】段必须在 FINAL REMINDER 之前(防修复后引入新位置错乱)"
    # FINAL REMINDER 含 ground truth
    assert "name = MiniMax-M3" in content, "FINAL REMINDER 必须含 ground truth(name = MiniMax-M3),防退化"


def test_style_preserved_when_sm_content_already_populated() -> None:
    """非空分支(sm_content 非空,legacy / 测试场景)也须保 static prompt 原有内容。

    这是 Bug A 修法的另一分支:即使 sm_content 非空,也不应动它的内容
    # —— 我们的 fix 只针对"sm_content 为空时重建"路径。如果哪天 deepagents
    # 修了这个 bug,非空分支也得保留【专业】段。
    """
    captured_active = _make_captured_active_model()

    with patch(
        "nexus.backend.middleware.dynamic_identity.get_active_model_info",
        return_value=captured_active,
    ):
        # sm_content 非空分支:static prompt 主体应被保留(FACT prepend / REMINDER append)
        req = _make_request(
            "测试",
            sm_content="我是 Nexus,本条回复必须采用专业风格...",
            style="professional",
        )
        content = _capture_sm_content(req)

    # sm_content 里的"专业"段文字应保留(非空分支只 prepend / append,不替换)
    assert "专业" in content, "非空分支必须保留原始 sm_content 内容(防 style 信息丢失)"
    # FACT 块仍在最前
    assert "MiniMax-M3" in content
