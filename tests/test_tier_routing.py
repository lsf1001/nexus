"""HarnessProfile tier 路由注册测试。

WHY 存在:
  2026-06-29 重构 —— 弱模型(MiniMax-M3)被 system prompt 硬指令锁死,导致
  投资问题答非所问。解决:不同 tier 模型用不同 system_prompt_suffix + 配套
  middleware,通过 deepagents HarnessProfile 按 ``provider:model`` 自动挂载。

deepagents HarnessProfile 注册接口:
  ``register_harness_profile(key: "provider:model", profile: HarnessProfile(...))``
  - 同 key 累加合并,不是覆盖
  - HarnessProfile 字段: system_prompt_suffix / base_system_prompt /
    excluded_tools / excluded_middleware / extra_middleware /
    tool_description_overrides
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_registry():
    """每次测试隔离 _HARNESS_PROFILES 和 _REGISTERED_SPECS,避免污染其它测试。

    WHY autouse:``register_harness_profile`` 是全局副作用,不隔离会污染
    后续测试。同时 ``register_tier_profiles()`` 用 ``_REGISTERED_SPECS``
    缓存幂等,需要清。
    """
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    from nexus.backend.profiles import tier_routing

    profiles_snapshot = dict(_HARNESS_PROFILES)
    specs_snapshot = dict(tier_routing._REGISTERED_SPECS)
    yield
    _HARNESS_PROFILES.clear()
    _HARNESS_PROFILES.update(profiles_snapshot)
    tier_routing._REGISTERED_SPECS.clear()
    tier_routing._REGISTERED_SPECS.update(specs_snapshot)


def test_register_weak_minimax_profile() -> None:
    """MiniMax-M3 注册到弱 profile:含弱模型 suffix(优先工具调用约束)。"""
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    from nexus.backend.profiles.tier_routing import register_tier_profiles

    register_tier_profiles()

    assert "openai:MiniMax-M3" in _HARNESS_PROFILES
    profile = _HARNESS_PROFILES["openai:MiniMax-M3"]
    suffix = profile.system_prompt_suffix or ""
    assert "优先使用工具" in suffix or "yandex_search" in suffix, f"弱模型 suffix 应含工具调用约束,实际:{suffix[:200]}"


def test_register_strong_agnes_profile() -> None:
    """agnes-2.0-flash 注册到强 profile:含强模型 suffix(允许自由答)。"""
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    from nexus.backend.profiles.tier_routing import register_tier_profiles

    register_tier_profiles()

    assert "openai:agnes-2.0-flash" in _HARNESS_PROFILES
    profile = _HARNESS_PROFILES["openai:agnes-2.0-flash"]
    suffix = profile.system_prompt_suffix or ""
    # 强模型 suffix 不含"必须用工具"硬约束(允许自主决定)
    assert "必须先调" not in suffix and "强制" not in suffix, f"强模型 suffix 不该含强工具约束,实际:{suffix[:200]}"


def test_register_is_idempotent() -> None:
    """重复注册不会报错(deepagents 同 key 累加合并语义)。"""
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    from nexus.backend.profiles.tier_routing import register_tier_profiles

    register_tier_profiles()
    first_count = len(_HARNESS_PROFILES)

    register_tier_profiles()
    second_count = len(_HARNESS_PROFILES)

    # 累加合并可能导致字段合并但 key 数量不变(取决于 deepagents 实现)
    # 这里至少验证不抛异常
    assert second_count >= first_count


def test_register_returns_dict_for_get_active_model() -> None:
    """register_tier_profiles() 返回 dict,供 /api/models/switch 后台调用检查。"""
    from nexus.backend.profiles.tier_routing import register_tier_profiles

    result = register_tier_profiles()
    assert isinstance(result, dict)
    # key 是已注册的 spec 列表
    assert "openai:MiniMax-M3" in result
    assert "openai:agnes-2.0-flash" in result
