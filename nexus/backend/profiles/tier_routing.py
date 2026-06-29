"""按 provider:model 注册 HarnessProfile —— Nexus tier 路由。

deepagents 0.6.14 真实 API(从 ``deepagents.profiles`` 公开 re-export):
  - :class:`HarnessProfile` 字段:
    - init_kwargs: 注入 init_chat_model 的 kwargs
    - base_system_prompt: 替换 BASE_AGENT_PROMPT(完整替换 base)
    - system_prompt_suffix: 拼到 base prompt 末尾
    - tool_description_overrides: 改写工具描述
    - pre_init / init_kwargs_factory: 副作用钩子
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
