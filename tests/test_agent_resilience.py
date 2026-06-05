"""``nexus.backend.agent`` 接入韧性层后的契约测试。

覆盖：
  - ``get_llm`` 默认返回 ``ResilientRunnable`` 包装（含 ``ainvoke`` / ``astream``）。
  - ``ResilientRunnable`` 通过 ``__getattr__`` 把未覆盖方法代理到底层 ChatOpenAI，
    以便 deepagents 内部调用 ``.bind`` / ``.with_fallbacks`` / ``.invoke`` 等不会断。
  - 显式传入 ``retry`` / ``timeout`` / ``fallback`` / ``fallback_policy`` 时使用传入值。
  - 原签名向后兼容：不传任何 resilience 参数时，依然能正常构造。
  - ``get_llm()`` 既无 ``model_name`` 也无 ``api_key`` 时仍抛 ``ValueError``。
  - ``create_subagents`` 输出的 ``code_writer`` / ``researcher`` 在 system prompt
    内携带 per-node 策略（重试次数 + 超时）。
"""

from __future__ import annotations

import pytest

from nexus.backend.agent import create_subagents, get_llm
from nexus.backend.llm.policies import FallbackPolicy, RetryPolicy, TimeoutPolicy
from nexus.backend.llm.wrapper import ResilientRunnable

# ----------------------------------------------------------------------
# get_llm：默认返回 ResilientRunnable
# ----------------------------------------------------------------------


class TestGetLlmDefault:
    """不显式传入韧性参数时的默认行为。"""

    def test_default_returns_resilient_runnable(self) -> None:
        """``get_llm`` 默认返回 ``ResilientRunnable``，暴露 ``ainvoke`` / ``astream``。"""
        llm = get_llm(model_name="test-model", api_key="k", api_base="https://x")
        assert isinstance(llm, ResilientRunnable)
        assert callable(llm.ainvoke)
        assert callable(llm.astream)

    def test_default_uses_default_policies(self) -> None:
        """不传 retry/timeout/fallback_policy 时使用默认 dataclass 实例。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        assert isinstance(llm.retry_policy, RetryPolicy)
        assert isinstance(llm.timeout_policy, TimeoutPolicy)
        assert isinstance(llm.fallback_policy, FallbackPolicy)
        # 不传 fallback 时 wrapper.fallback 为 None
        assert llm.fallback is None


# ----------------------------------------------------------------------
# __getattr__ 代理
# ----------------------------------------------------------------------


class TestResilientRunnableProxy:
    """deepagents 兼容性：未在 wrapper 显式定义的方法/属性 → 代理到 primary。"""

    def test_unknown_attribute_proxies_to_chatopenai(self) -> None:
        """``llm.model_name`` 通过 ``__getattr__`` 代理到底层 ``ChatOpenAI.model_name``。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        # ChatOpenAI 暴露 model 和 model_name；ResilientRunnable 自身没有
        assert llm.model_name == "m"

    def test_bind_method_is_proxied(self) -> None:
        """``llm.bind(stop=...)`` 应代理到 ChatOpenAI.bind，返回 LangChain 的绑定对象
        而非 ResilientRunnable（验证 ``__getattr__`` 没有把方法吞掉）。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        bound = llm.bind(stop=["STOP"])
        # bind 返回的不应是 ResilientRunnable —— 它来自底层 LangChain
        assert not isinstance(bound, ResilientRunnable)
        # 应该是某种带 ``invoke`` / ``ainvoke`` 的可运行对象
        assert hasattr(bound, "ainvoke") or hasattr(bound, "invoke")

    def test_proxy_raises_attribute_error_for_truly_missing(self) -> None:
        """``__getattr__`` 在底层也没有该属性时必须抛 ``AttributeError``，
        不要无脑返回 ``None`` 让调用方误以为存在该方法。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        with pytest.raises(AttributeError):
            _ = llm.this_attribute_truly_does_not_exist_xyz

    def test_ainvoke_is_not_proxied(self) -> None:
        """``ResilientRunnable`` 自己定义了 ``ainvoke``，``__getattr__`` 不应抢走。

        通过比对：``llm.ainvoke`` 应该是 wrapper 自己的 bound method，
        和 ``llm._primary.ainvoke`` 不是同一个对象。
        """
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        # llm.ainvoke 来自 ResilientRunnable，与底层 ChatOpenAI.ainvoke 不同
        assert llm.ainvoke.__func__ is ResilientRunnable.ainvoke


# ----------------------------------------------------------------------
# get_llm：自定义韧性参数
# ----------------------------------------------------------------------


class TestGetLlmWithCustomPolicies:
    """显式传入 retry / timeout / fallback / fallback_policy 时按传入值生效。"""

    def test_custom_retry_and_timeout(self) -> None:
        """传入自定义 RetryPolicy / TimeoutPolicy 时按传入对象使用。"""
        custom_retry = RetryPolicy(max_attempts=5, base_delay=0.05)
        custom_timeout = TimeoutPolicy(per_call=10.0, per_stream=30.0)
        llm = get_llm(
            model_name="m",
            api_key="k",
            api_base="https://x",
            retry=custom_retry,
            timeout=custom_timeout,
        )
        assert llm.retry_policy is custom_retry
        assert llm.timeout_policy is custom_timeout

    def test_custom_fallback_policy(self) -> None:
        """传入自定义 FallbackPolicy 时按传入对象使用。"""
        custom_fp = FallbackPolicy()
        llm = get_llm(
            model_name="m",
            api_key="k",
            api_base="https://x",
            fallback_policy=custom_fp,
        )
        assert llm.fallback_policy is custom_fp

    def test_fallback_secondary_llm_attached(self) -> None:
        """显式传入 ``fallback`` 时，wrapper 持有该备用 LLM 的引用。"""
        # 先用 get_llm 构造一个 ChatOpenAI（取 _primary 拿到原生对象）
        fallback_wrapped = get_llm(
            model_name="backup", api_key="k2", api_base="https://y"
        )
        fallback_chat = fallback_wrapped._primary
        llm = get_llm(
            model_name="primary",
            api_key="k1",
            api_base="https://x",
            fallback=fallback_chat,
        )
        assert llm.fallback is fallback_chat


# ----------------------------------------------------------------------
# 向后兼容：原签名 / 异常路径
# ----------------------------------------------------------------------


class TestGetLlmBackwardCompat:
    """保持原 ``get_llm`` 签名和异常行为，调用方零感知。"""

    def test_missing_model_and_api_key_raises(self) -> None:
        """既无 model_name 也无 api_key 时仍抛 ValueError。"""
        # 注意：调用方甚至可能完全不传参（CONFIG 也没 key 的极端情况），
        # 这里显式让两个参数都缺失。
        with pytest.raises(ValueError, match="model_name and api_key"):
            get_llm()

    def test_temperature_param_is_threaded_through(self) -> None:
        """传入 temperature 时正确透传给底层 ChatOpenAI。"""
        llm = get_llm(
            model_name="m",
            api_key="k",
            api_base="https://x",
            temperature=0.42,
        )
        # 通过代理读取底层 ChatOpenAI 的 temperature 字段
        assert llm.temperature == pytest.approx(0.42)


# ----------------------------------------------------------------------
# create_subagents：per-node 策略写入 system prompt
# ----------------------------------------------------------------------


class TestCreateSubagentsPolicies:
    """``create_subagents`` 把 per-node 重试/超时策略写入 system prompt。"""

    def test_subagents_have_expected_names(self) -> None:
        """``create_subagents`` 至少包含 code_writer 与 researcher。"""
        subs = create_subagents()
        names = {sa["name"] for sa in subs}
        assert {"code_writer", "researcher"}.issubset(names)

    def test_code_writer_carries_no_retry_300s(self) -> None:
        """code_writer 的 system_prompt 描述 max_retries=0 + timeout=300。"""
        subs = create_subagents()
        cw = next(sa for sa in subs if sa["name"] == "code_writer")
        prompt = cw.get("system_prompt") or ""
        # 接受多种表达：300 或 300s 都行
        assert "300" in prompt, f"expect '300' (timeout) in prompt: {prompt!r}"
        # 重试次数：0 次
        assert "0 次重试" in prompt or "0次重试" in prompt or "no retry" in prompt.lower(), (
            f"expect explicit zero-retry hint in prompt: {prompt!r}"
        )

    def test_researcher_carries_two_retries_120s(self) -> None:
        """researcher 的 system_prompt 描述 max_retries=2 + timeout=120。"""
        subs = create_subagents()
        r = next(sa for sa in subs if sa["name"] == "researcher")
        prompt = r.get("system_prompt") or ""
        assert "120" in prompt, f"expect '120' (timeout) in prompt: {prompt!r}"
        assert "2 次重试" in prompt or "2次重试" in prompt, (
            f"expect explicit two-retries hint in prompt: {prompt!r}"
        )
