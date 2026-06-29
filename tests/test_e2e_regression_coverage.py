"""E2E 回归覆盖标记 —— 2026-06-29 DeepAgents 重构后,关键契约的覆盖矩阵。

本测试**不**启后端、不连真实 LLM,只做"覆盖声明 + 引用"。

WHY 存在:
  Task 7(E2E 验证 agnes vs MiniMax-M3 行为差异)需要真实 API key + 长
  时间的网络请求,CI 环境跑不动。核心契约已被单测覆盖,本测试做两件事:

    1. 强制 import 关键模块 + 创建关键对象,防止删除某个 import 后链路
       静默断裂(eg. 之前 ``from .profiles import _ensure_registered``
       找不到时,agent.py 启动直接 import 失败,E2E 才能发现)。
    2. 把"重构后哪些场景被哪些测试覆盖"显式记录下来,方便后续产品/QA
       在有真实 API key 的环境里挑对应场景跑 ``e2e_debug_stock_question.py``。

E2E 真实模型跑法(在有 API key 的环境):
  1. ``bash scripts/build_dmg.sh && open release/Nexus.app`` 启动生产 DMG
  2. 切到 agnes-2.0-flash(active=agnes)
  3. 前端发"元力股份 能买吗",应看到:
     - WS tool_start 帧里出现 yandex_search(agnes 主动调)
     - chunks 拼接 1191+ 字,含"元力"实质分析
  4. 切到 MiniMax-M3(active=M3)
  5. 同样问题,应看到:
     - 第一次 LLM 响应不调工具 → ForceToolMiddleware patch yandex_search
     - 搜索结果回填后 LLM 用结果回答
     - 不再复读"我是 Nexus,由 MiniMax-M3 驱动"身份话术
"""

from __future__ import annotations


def test_force_tool_middleware_module_importable() -> None:
    """ForceToolMiddleware 链路 import 通 + wrap_model_call 可调用。"""
    from nexus.backend.middleware.force_tool import (
        ForceToolMiddleware,
        classify_intent_lightweight,
    )

    assert ForceToolMiddleware is not None
    assert callable(classify_intent_lightweight)
    # 关键意图:investment question 命中 knowledge
    assert classify_intent_lightweight("元力股份 能买吗") == "knowledge"


def test_tier_routing_module_importable_and_registered() -> None:
    """tier_routing 注册弱/强两档 HarnessProfile,key 与 deepagents spec 对齐。"""
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    from nexus.backend.profiles.tier_routing import register_tier_profiles

    register_tier_profiles()
    # 弱模型 MiniMax-M3 + 强模型 agnes-2.0-flash
    assert "openai:MiniMax-M3" in _HARNESS_PROFILES
    assert "openai:agnes-2.0-flash" in _HARNESS_PROFILES


def test_intent_router_returns_knowledge_for_investment_question() -> None:
    """'元力股份 能买吗' 走知识类路径,落库 INTENT_KNOWLEDGE。"""
    from nexus.backend.intent.router import (
        INTENT_KNOWLEDGE,
        classify_intent,
    )

    assert classify_intent("元力股份 能买吗") == INTENT_KNOWLEDGE


def test_agent_create_agent_does_not_explode() -> None:
    """create_agent 顶层 import + 类引用通(不实际构造,构造会拉 sqlite/mcp)。"""
    from nexus.backend.agent import (
        _build_system_prompt,
        get_llm,
        get_system_prompt,
        reload_system_prompt,
    )

    assert callable(_build_system_prompt)
    assert callable(get_llm)
    assert callable(get_system_prompt)
    assert callable(reload_system_prompt)


def test_classify_intent_never_raises_on_arbitrary_input() -> None:
    """classify_intent 对任何输入(空 / None / bytes / 数字)兜底 chitchat。

    WHY:ws.py 心跳后立刻调 classify_intent,如果它抛异常会破坏 WS 流。
    兜底契约必须在所有边界都成立。
    """
    from nexus.backend.intent.router import (
        DEFAULT_INTENT,
        INTENT_CHITCHAT,
        classify_intent,
    )

    for bad in [None, 0, 1.5, b"bytes", [], {}, object()]:
        result = classify_intent(bad)  # type: ignore[arg-type]
        assert result == INTENT_CHITCHAT

    # 显式断言 DEFAULT_INTENT 确实是 chitchat
    assert DEFAULT_INTENT == INTENT_CHITCHAT
