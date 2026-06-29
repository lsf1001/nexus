"""Nexus 自定义的 DeepAgents profile 注册中心。

WHY 存在:
  对齐 DeepAgents 框架设计 —— 不同 tier 模型用不同 system_prompt_suffix +
  配套 middleware,通过 deepagents :class:`HarnessProfile` 按 ``provider:model``
  自动挂载。Nexus 自造模块只补 deepagents 没有的(深 agents 的 profile 注册
  API 是内部命名空间,本 package 提供一个稳定外壳 + Nexus 业务级 tier 路由)。

模块布局:
  - 本 ``__init__`` —— 旧版 ``register_nexus_profiles`` 兼容层(2026-06-29
    起降级为 no-op 占位,保留 API 形状供旧测试 / 调用方零感知)
  - :mod:`nexus.backend.profiles.tier_routing` —— 实际 deepagents profile
    注册,按 provider:model 区分弱/强模型

WHY 旧版 API 留在 package ``__init__`` 顶层(不在子模块):
  测试断言 ``profiles_module._PROFILES_REGISTERED is True``,``profiles_module``
  是 ``nexus.backend.profiles`` package。如果在子模块 ``legacy.py`` 里
  定义 + 顶层 ``from .legacy import _PROFILES_REGISTERED``,那名字是值
  复制,``legacy._PROFILES_REGISTERED = True`` 不会反映到 package 属性
  上(测试注释叫"True trap")。把状态留在 ``__init__`` 顶层,``global``
  修改的就是 package 全局,属性查找看到的是同一份。
"""

from __future__ import annotations

import logging

from nexus.backend.profiles import tier_routing
from nexus.backend.profiles.tier_routing import register_tier_profiles

logger = logging.getLogger(__name__)


# 幂等标志:防止 main.py + tests + 重建路径多调一次。
# 重要:这个变量必须定义在 package 顶层,而不是子模块。详见模块 docstring
# "True trap" 解释。
_PROFILES_REGISTERED = False


def register_nexus_profiles() -> None:
    """Nexus 默认 profile 注册 —— 当前是 no-op 占位。

    历史行为:注册 ``minimax`` / ``minimax:MiniMax-M3`` 的 ProviderProfile
    (init_kwargs) + HarnessProfile(nexus_suffix + general_purpose_subagent)。

    2026-06-29 重构后:实际注册职责迁到
    :func:`register_tier_profiles`,由 ``create_deep_agent()`` 之前显式调用。
    本函数仅设幂等标志保持 API 兼容。
    """
    global _PROFILES_REGISTERED
    if _PROFILES_REGISTERED:
        return
    _PROFILES_REGISTERED = True
    logger.debug("register_nexus_profiles: 实际注册已迁至 register_tier_profiles,本函数为 no-op 占位")


def reset_profiles_for_test() -> None:
    """重置幂等标志 —— 测试用,允许重新调 register_nexus_profiles。"""
    global _PROFILES_REGISTERED
    _PROFILES_REGISTERED = False


def _ensure_registered() -> None:
    """内部 helper:首次调用时自动注册。"""
    if not _PROFILES_REGISTERED:
        register_nexus_profiles()


__all__ = [
    "_PROFILES_REGISTERED",
    "_ensure_registered",
    "register_nexus_profiles",
    "register_tier_profiles",
    "reset_profiles_for_test",
    "tier_routing",
]
