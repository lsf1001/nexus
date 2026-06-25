"""Nexus 在 DeepAgents 0.6.8+ 的 ProviderProfile / HarnessProfile 注册中心。

WHY 注册 ProviderProfile + HarnessProfile:
  - ProviderProfile 控制 LLM 构造阶段(init_chat_model kwargs / pre_init 副作用)。
  - HarnessProfile 控制 Agent 运行阶段(prompt 后缀 / 工具排除 / subagent 调整)。
  - 不同 LLM 模型对 deepagents 框架的兼容性差异(上下文长度 / tool_choice
    语义 / reasoning 输出)在 profile 里集中管理,而不是散在 ``get_llm()`` 里。

设计:
  - 注册幂等 — ``register_*`` 内部就是 merge,重复注册覆盖前值。
  - 默认开启 — 启动 nexus 时调用 :func:`register_nexus_profiles` 一次。
  - 用户覆盖 — 测试 / 评测场景可显式调 ``register_*`` 覆盖。

注册键约定(deepagents 0.6.8 规则):
  - 顶层 key(如 ``"minimax"``)→ 匹配该 provider 所有模型
  - ``provider:model`` 完整 key(如 ``"minimax:MiniMax-M3"``)→ 仅匹配该模型
  - 后者优先级更高

WHY 选 ``HarnessProfileConfig``(不是 ``HarnessProfile``):
  - Config 是声明式子集,字段都是 string / bool / list,易序列化 / 易 review。
  - ``HarnessProfile`` 支持 ``extra_middleware``(class 实例),Nexus 暂时
    用不到,留 extension 接口给未来。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# 注册幂等:防止 main.py + tests + CLI 三处都调一次导致重复 / 冲突
_PROFILES_REGISTERED = False


def register_nexus_profiles() -> None:
    """注册 Nexus 使用的 LLM provider + harness profiles。

    WHY 模块级单例:deepagents 内部维护一个 registry,重复注册相同 key 会
    触发 merge,但调用次数多了浪费。``_PROFILES_REGISTERED`` 守住"只做一次"。

    注:MiniMax-M3 默认 profile 的 system_prompt_suffix 是 Nexus 风格提示
    ("先读再写 / 行为侧验证 / 中文回复"),跨 LLM 适配。Claude / GPT 模型
    用 deepagents 内置 profile,不需要额外注册。
    """
    global _PROFILES_REGISTERED
    if _PROFILES_REGISTERED:
        return

    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        HarnessProfileConfig,
        ProviderProfile,
        register_harness_profile,
        register_provider_profile,
    )

    # ------------------------------------------------------------------
    # ProviderProfile:LLM 构造阶段(init_chat_model kwargs)
    # ------------------------------------------------------------------
    # MiniMax-M3(Anthropic 兼容 API):需要 base_url + 显式 auth_token,
    # init_kwargs 写进 ``ChatOpenAI`` 的 openai_api_* 参数。Nexus 用
    # 自建 ResilientRunnable 包装(见 ``llm/wrapper.py``),这里只设默认值。
    register_provider_profile(
        "minimax",
        ProviderProfile(
            init_kwargs={
                # 默认温度:小改用 0.3(精准),大改用 0.7(发散);具体 task 调
                # ``get_llm(temperature=...)`` 覆盖。
                "temperature": 0.7,
                "max_tokens": 8192,
            },
        ),
    )
    # 为具体的 MiniMax-M3 模型再注册一份,优先于 provider 级。
    # WHY 双层:MiniMax-M3 的 max_tokens / reasoning 行为跟其他 Anthropic 兼容
    # 模型不一样,模型级 profile 覆盖 provider 级更安全。
    register_provider_profile(
        "minimax:MiniMax-M3",
        ProviderProfile(
            init_kwargs={
                "temperature": 0.7,
                "max_tokens": 16384,  # M3 支持更长输出
            },
        ),
    )

    # ------------------------------------------------------------------
    # HarnessProfile:Agent 运行阶段(prompt / 工具 / subagent 调整)
    # ------------------------------------------------------------------
    # Nexus 通用 harness 配置:所有 minimax 模型默认继承。
    # - system_prompt_suffix:Nexus 行为约定(中文回复 / 行为验证 / 持续到完成)
    # - general_purpose_subagent:开启 deepagents 内置"通用"subagent,跟我们的
    #   ``code_writer`` / ``researcher`` 互补,LLM 需要临时"问一下"时用它。
    nexus_suffix = (
        "\n\n【Nexus 行为约定】\n"
        "- 用简体中文回复。\n"
        "- 完成态 = 行为侧验证成功(文件真落盘 / 接口真返回 / 测试真过),不是\n"
        "  LLM 嘴上说『我完成了』。\n"
        "- 持续工作直到任务真完成;不要中途停下来『先这样吧』。"
    )

    register_harness_profile(
        "minimax",
        HarnessProfileConfig(
            system_prompt_suffix=nexus_suffix,
            general_purpose_subagent=GeneralPurposeSubagentProfile(
                enabled=True,
                description=(
                    "通用 subagent:主代理需要临时研究 / 试探 / 子任务时调它。"
                    "它有完整 filesystem 工具,适合临时性、不需要写主流程的工作。"
                ),
            ),
        ),
    )

    # 也可以用 HarnessProfile(完整版)覆盖具体模型 — 留给未来。
    # 当前默认行为已够用,先不在 create_agent 启动期做"如果 model=X 则 Y"。
    del HarnessProfile  # noqa: F841 — 留给未来扩展,避免 ruff 报 unused

    _PROFILES_REGISTERED = True
    logger.info("Nexus profiles registered: minimax / minimax:MiniMax-M3")


def reset_profiles_for_test() -> None:
    """重置注册标记 — 测试用,允许重新注册不同 profile。"""
    global _PROFILES_REGISTERED
    _PROFILES_REGISTERED = False


def _ensure_registered() -> None:
    """内部 helper:首次调用时自动注册(Nexus 默认行为)。"""
    if not _PROFILES_REGISTERED:
        register_nexus_profiles()
