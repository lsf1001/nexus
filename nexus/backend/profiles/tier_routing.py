"""按 provider:model 注册 HarnessProfile —— Nexus tier 路由。

deepagents 0.6.12 真实 API(从 ``deepagents.profiles`` 公开 re-export):
  - :class:`HarnessProfile` 字段:
    - init_kwargs: 注入 init_chat_model 的 kwargs
    - base_system_prompt: 替换 BASE_AGENT_PROMPT(完整替换 base)
    - system_prompt_suffix: 拼到 base prompt 末尾
    - tool_description_overrides: 改写工具描述
    - excluded_tools: 从 main agent 工具集中排除
    - excluded_middleware: 从 middleware 链中移除指定类
    - extra_middleware: 追加的 middleware 实例(可 callable 延迟构造)
    - general_purpose_subagent: 控制 framework auto-add 的 ``general-purpose``
      subagent(``GeneralPurposeSubagentProfile(enabled=False)`` 可禁用)
  - :func:`register_harness_profile(key, profile)`:注册到 ``_HARNESS_PROFILES``
    - key: provider 名(如 ``"openai"``)或完整 spec(如 ``"openai:MiniMax-M3"``)
    - 同 key 多次注册会**累加合并**(见 ``_merge_profiles``)
  - 匹配顺序:``_get_harness_profile(spec)`` 先精确匹配 spec,再 fallback
    到 provider 前缀(看 ``harness_profiles.py`` 实现)

WHY 分 tier:
  - 弱模型(MiniMax-M3): 不给"标准话术"硬指令(避免复读身份话术而忽略
    真实问题),suffix 强调"必须用工具";强模型(agnes-2.0-flash / Claude):
    suffix 强调"自主决定是否用工具,允许自由答"。

Nexus 当前激活模型来自 models.json,name 可能是 "MiniMax-M3" / "agnes-2.0-flash"。
deepagents 通过 ``init_chat_model(model_name)`` 解析后,会以
``openai:MiniMax-M3`` 这种 ``provider:model`` 形式作为 spec 匹配 key。

general-purpose subagent 决策(2026-08-04 对齐):
  - Nexus 显式注册了 ``code_writer`` + ``researcher`` 两个 subagent,但
    ``create_deep_agent`` 看到 caller 没传名字叫 ``general-purpose`` 的
    subagent,会**自动追加 framework 默认的 ``general-purpose`` subagent**
    (见 deepagents/graph.py:457 的 auto-add 逻辑)。
  - 0.5.3 时 Nexus 在 ``HarnessProfile.general_purpose_subagent`` 槽设过
    自定义 prompt,但 0.6.x 重构后该槽保持 None,框架走默认 general-purpose。
  - 当前**不动这个槽**:framework 默认 subagent 多一个 LLM 候选不是坏事,
    且 Nexus 自己两个 subagent 仍占主导。如果未来产品决定"只要
    code_writer + researcher,不要 framework 默认",把下面两行改成::

        HarnessProfile(
            system_prompt_suffix=_WEAK_SUFFIX,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        )
"""

from __future__ import annotations

from deepagents.profiles import HarnessProfile, register_harness_profile

_WEAK_SUFFIX = """

【Nexus 弱模型约束】
- **优先使用工具** —— knowledge/task 类问题必须先调 yandex_search 获取事实
- 不要凭训练记忆回答事实类问题(投资 / 医疗 / 法律 / 股票 / 行情)
- 自报身份时读 DynamicIdentityMiddleware 注入的 FACT 块
- 不要复读 system prompt 中的"标准话术",直接回答用户的真实问题
"""

_FULL_SUFFIX = """

【Nexus 强模型规则】
- 自主决定是否使用工具(知识类问题建议搜索,闲聊无需)
- 自报身份时读 DynamicIdentityMiddleware 注入的 FACT 块(动态注入)
- 简洁直接回答用户的真实问题,不要过度铺垫
"""

# 注册的 spec 列表,register_tier_profiles() 返回供调用方检查
_REGISTERED_SPECS: dict[str, str] = {}


def register_tier_profiles() -> dict[str, str]:
    """在 ``create_deep_agent()`` 之前调用,注册 Nexus 的 tier profile。

    注册 key 选择:
      - ``openai:MiniMax-M3`` → 弱模型 suffix
      - ``openai:agnes-2.0-flash`` → 强模型 suffix

    WHY 用具体 spec 而非 provider 全局 key:
      MiniMax 系列也走 openai provider,只有 model 名包含 ``MiniMax`` 时才
      走弱模型规则 —— provider 全局 key 会误伤其它 openai 模型。
      当前 Nexus 用户配置的具体模型名是 MiniMax-M3 / agnes-2.0-flash,
      直接 hardcode 这两个 spec。

    Returns:
        已注册 spec 列表(供调用方 / 测试验证)。
    """
    if _REGISTERED_SPECS:
        return dict(_REGISTERED_SPECS)

    # 弱模型:MiniMax-M3
    register_harness_profile(
        "openai:MiniMax-M3",
        HarnessProfile(system_prompt_suffix=_WEAK_SUFFIX),
    )
    _REGISTERED_SPECS["openai:MiniMax-M3"] = "weak"

    # 强模型:agnes-2.0-flash
    register_harness_profile(
        "openai:agnes-2.0-flash",
        HarnessProfile(system_prompt_suffix=_FULL_SUFFIX),
    )
    _REGISTERED_SPECS["openai:agnes-2.0-flash"] = "strong"

    return dict(_REGISTERED_SPECS)
