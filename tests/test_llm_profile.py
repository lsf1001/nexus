"""``ResilientRunnable._resolve_model_profile`` 的契约测试。

为什么需要这个测试:Nexus 把"NEXUS_CONTEXT_WINDOW = 200K"作为唯一可配变量,
通过 ``_resolve_model_profile`` 把 ``max_input_tokens`` 喂给 deepagents 的
``compute_summarization_defaults``,从而让自动压缩触发阈值 = context_window × 0.85。

测试覆盖三类路径:
  1. 正常:NEXUS_CONTEXT_WINDOW=200000 → profile.max_input_tokens=200000
  2. 边界:NEXUS_CONTEXT_WINDOW=32000 → profile.max_input_tokens=32000
  3. 异常:env 注入非法值(如 "abc") → 走 CONFIG 兜底逻辑

WHY:这条契约是 Codex 删除显式 SummarizationMiddleware 后的**唯一** trigger
驱动点。若 profile 返回错值,deepagents 会 fallback 到 170K 固定 trigger(对
200K 模型几乎不触发),原"早压保护"直接失效。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nexus.backend.llm.wrapper import ResilientRunnable


@pytest.fixture
def resilient() -> ResilientRunnable:
    """ResilientRunnable 实例,primary 用 mock(spec=[]) 占位 — 不调 primary。

    WHY ``MagicMock(spec=[])``:spec=[] 让 mock 不暴露任意属性,意外调到
    primary 的接口会 AttributeError,比静默 mock 更早暴露问题。
    """
    primary = MagicMock(spec=[])
    return ResilientRunnable(primary=primary)  # type: ignore[arg-type]


@pytest.fixture
def set_context_window(monkeypatch: pytest.MonkeyPatch):
    """设 ``NEXUS_CONTEXT_WINDOW`` 并**重载** ``CONFIG`` 模块级字典。

    用法::

        def test_xxx(resilient, set_context_window):
            set_context_window("128000")           # 设值并重载
            set_context_window(None)               # delenv + 重载(走默认值)
            assert resilient._resolve_model_profile()["max_input_tokens"] == 200_000

    WHY:``CONFIG`` 是模块级常量,pytest 启动时一次性 ``load_config()``;
    ``monkeypatch.setenv`` 只改 env,不重载 ``CONFIG``。factory 模式让
    ``setenv`` 一定在 ``load_config`` 之前,避免顺序 bug。

    WHY ``value=None`` 走 ``delenv``:测试"默认值"路径时必须确保 env 没有
    这个 key(否则 pytest runner shell 注入的值会污染)。delenv + raising=False
    在 key 不存在时也不报错。
    """
    import nexus.backend.config as _cfg

    def _set(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("NEXUS_CONTEXT_WINDOW", raising=False)
        else:
            monkeypatch.setenv("NEXUS_CONTEXT_WINDOW", value)
        monkeypatch.setattr(_cfg, "CONFIG", _cfg.load_config())

    return _set


class TestResolveModelProfileNormal:
    """正常路径:NEXUS_CONTEXT_WINDOW 已设置。"""

    def test_default_200k(self, resilient: ResilientRunnable, set_context_window) -> None:
        """NEXUS_CONTEXT_WINDOW 未设置 → 用默认 200000。

        ``set_context_window(None)`` 触发 delenv + load_config,env 不存在
        时 ``os.environ.get(..., "200000")`` 走默认值。
        """
        set_context_window(None)
        profile = resilient._resolve_model_profile()
        assert profile is not None
        assert profile["max_input_tokens"] == 200_000

    def test_explicit_env_override(self, resilient: ResilientRunnable, set_context_window) -> None:
        """NEXUS_CONTEXT_WINDOW=128000 → profile.max_input_tokens=128000。"""
        set_context_window("128000")
        profile = resilient._resolve_model_profile()
        assert profile is not None
        assert profile["max_input_tokens"] == 128_000


class TestResolveModelProfileBoundary:
    """边界条件:极端 context window。"""

    def test_small_context_32k(self, resilient: ResilientRunnable, set_context_window) -> None:
        """NEXUS_CONTEXT_WINDOW=32000 → profile.max_input_tokens=32000。
        WHY:历史值,测试要确保旧用户没改 env 时不会突然 200K。
        """
        set_context_window("32000")
        profile = resilient._resolve_model_profile()
        assert profile is not None
        assert profile["max_input_tokens"] == 32_000

    def test_huge_context_2m(self, resilient: ResilientRunnable, set_context_window) -> None:
        """NEXUS_CONTEXT_WINDOW=2000000(Gemini 1.5 Pro)→ 折算正确。"""
        set_context_window("2000000")
        profile = resilient._resolve_model_profile()
        assert profile is not None
        assert profile["max_input_tokens"] == 2_000_000


class TestResolveModelProfileError:
    """异常路径:env 注入非法值。"""

    def test_invalid_env_caught_at_config_load(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NEXUS_CONTEXT_WINDOW=abc → ``load_config()`` 抛 ValueError,不应静默。

        WHY:这是用户配置错误,静默回退会让 trigger 计算错位,导致自动压缩
        永远不触发。应当显式报错让用户发现;拦截点放在最早(load_config)
        而不是 profile 解析阶段,便于快速定位。
        """
        monkeypatch.setenv("NEXUS_CONTEXT_WINDOW", "abc")
        import nexus.backend.config as _cfg

        with pytest.raises(ValueError, match="invalid literal"):
            _cfg.load_config()


class TestResolveModelProfileDrivesDeepagents:
    """契约验证:_resolve_model_profile 的返回值喂给 deepagents 后能算出预期 trigger。"""

    def test_deepagents_fraction_85_yields_170k_for_200k(
        self, resilient: ResilientRunnable, set_context_window
    ) -> None:
        """200K profile × deepagents fraction 0.85 = 170K trigger。

        这是**核心契约**:Codex 删除显式 SummarizationMiddleware 后,Nexus
        必须靠这条链确保自动压缩在 200K 模型上有意义触发。
        """
        set_context_window("200000")
        profile = resilient._resolve_model_profile()
        assert profile is not None

        max_input = profile["max_input_tokens"]
        # deepagents ``compute_summarization_defaults`` 看到 max_input_tokens
        # 时硬编码 ``trigger=("fraction", 0.85)``,实际 trigger = max × 0.85
        expected_trigger = int(max_input * 0.85)
        assert expected_trigger == 170_000

    def test_profile_drives_context_window_for_estimate(self, resilient: ResilientRunnable, set_context_window) -> None:
        """profile.max_input_tokens 与 CONFIG.context_window 始终一致。

        WHY:避免后续 refactor 把 wrapper 和 config 解耦时,出现"profile 200K
        但 ws._estimate_tokens 默认 32K"的不一致(那会让用户看 UI 提示和实际
        触发逻辑用两套窗口值,debug 时极难定位)。
        """
        set_context_window("200000")
        import nexus.backend.config as _cfg

        profile = resilient._resolve_model_profile()
        assert profile is not None
        assert profile["max_input_tokens"] == int(_cfg.CONFIG.get("context_window"))
