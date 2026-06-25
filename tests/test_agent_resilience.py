"""``nexus.backend.agent`` 接入韧性层后的契约测试。

覆盖：
  - ``get_llm`` 默认返回 ``ResilientRunnable`` 包装（含 ``ainvoke`` / ``astream``），
    同时是 ``langchain_core.language_models.BaseChatModel`` 子类。
  - ``ResilientRunnable`` 不再靠 ``__getattr__`` 代理未知属性；底层字段通过
    ``.primary`` / ``.fallback`` 访问。bind 类方法返回 :class:`ResilientRunnable`。
  - 显式传入 ``retry`` / ``timeout`` / ``fallback`` / ``fallback_policy`` 时使用传入值。
  - 原签名向后兼容：不传任何 resilience 参数时，依然能正常构造。
  - ``get_llm()`` 既无 ``model_name`` 也无 ``api_key`` 时仍抛 ``ValueError``。
  - ``create_subagents`` 输出的 ``code_writer`` / ``researcher`` 在 system prompt
    内携带 per-node 策略（重试次数 + 超时）。
  - 端到端：``create_agent`` 内部把 :class:`ResilientRunnable` 喂给
    ``create_deep_agent``，deepagents 看到的就是 ``BaseChatModel``。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

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
# BaseChatModel 集成契约
# ----------------------------------------------------------------------


class TestResilientRunnableIsBaseChatModel:
    """deepagents 集成：``isinstance(llm, BaseChatModel)`` 必须为 True。"""

    def test_isinstance_basechatmodel(self) -> None:
        """``ResilientRunnable`` 继承 ``BaseChatModel``，满足 deepagents 的契约。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        assert isinstance(llm, BaseChatModel)
        assert isinstance(llm, ResilientRunnable)

    def test_primary_attribute_accessible(self) -> None:
        """底层 ChatOpenAI 字段不再走 ``__getattr__`` 代理，必须通过 ``.primary`` 访问。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        # 自身不再有 model_name（无 __getattr__ 代理）
        with pytest.raises(AttributeError):
            _ = llm.model_name
        # 通过 .primary 访问到底层 ChatOpenAI
        assert llm.primary.model_name == "m"

    def test_temperature_accessible_via_primary(self) -> None:
        """temperature 等 ChatOpenAI 字段通过 ``.primary`` 访问。"""
        llm = get_llm(
            model_name="m",
            api_key="k",
            api_base="https://x",
            temperature=0.42,
        )
        with pytest.raises(AttributeError):
            _ = llm.temperature
        assert llm.primary.temperature == pytest.approx(0.42)

    def test_unknown_attribute_still_raises(self) -> None:
        """未知属性仍抛 ``AttributeError``（Pydantic BaseModel 的默认行为）。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        with pytest.raises(AttributeError):
            _ = llm.this_attribute_truly_does_not_exist_xyz

    def test_ainvoke_is_own_method(self) -> None:
        """``ResilientRunnable`` 自己定义 ``ainvoke``，不是从 primary 借的。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        assert llm.ainvoke.__func__ is ResilientRunnable.ainvoke

    def test_llm_type_is_derived_from_primary(self) -> None:
        """``_llm_type`` 组合 ``resilient_`` + 底层类型，便于 langsmith 识别。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        assert llm._llm_type.startswith("resilient_")
        assert llm._llm_type.endswith(llm.primary._llm_type)


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
        fallback_wrapped = get_llm(model_name="backup", api_key="k2", api_base="https://y")
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
        assert "2 次重试" in prompt or "2次重试" in prompt, f"expect explicit two-retries hint in prompt: {prompt!r}"


# ----------------------------------------------------------------------
# 端到端：create_agent -> create_deep_agent(model=ResilientRunnable)
# ----------------------------------------------------------------------


class TestCreateAgentIntegration:
    """``create_agent`` 把 ``ResilientRunnable`` 喂给 deepagents，不应再崩溃。"""

    # 契约只验 model= 是不是 ResilientRunnable,后端是 sqlite 还是 memory 都不影响。
    # 强制走 memory 避开 aiosqlite 后台线程 + sync sqlite3 同库持锁死锁。
    @pytest.fixture(autouse=True)
    def _disable_sqlite_backends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXUS_STORE", "memory")
        monkeypatch.setenv("NEXUS_CHECKPOINTER", "memory")

    def test_create_agent_uses_resilient_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """端到端：``get_llm`` 包装后的 ``ResilientRunnable`` 作为 ``create_deep_agent`` 的 model 传入。

        修复前 ``ResilientRunnable`` 不是 ``BaseChatModel`` 子类，``resolve_model`` 走
        fallback 路径时调 ``.count(":")`` 触发 ``AttributeError``。
        """
        # 不需要真实 API key：create_deep_agent 已被 patch，不实际跑。
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        # agent.py 内部用 `from deepagents import create_deep_agent`，函数执行时
        # 才解析符号；patch 源模块 deepagents.create_deep_agent 即可拦截。
        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")
            called_kwargs = mock_create.call_args.kwargs
            model = called_kwargs["model"]
            # 必须是 ResilientRunnable（保留韧性）
            assert isinstance(model, ResilientRunnable)
            # 同时也是 BaseChatModel（满足 deepagents isinstance 契约）
            assert isinstance(model, BaseChatModel)


class TestBindMethodsPreserveResilience:
    """bind 类方法必须返回 :class:`ResilientRunnable`，否则韧性会旁路。"""

    def test_bind_returns_resilient(self) -> None:
        """``llm.bind(stop=...)`` 返回 :class:`ResilientRunnable`。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        bound = llm.bind(stop=["STOP"])
        assert isinstance(bound, ResilientRunnable)
        # 仍具备韧性入口
        assert callable(bound.ainvoke)
        assert callable(bound.astream)

    def test_bind_tools_returns_resilient(self) -> None:
        """``llm.bind_tools([])`` 返回 :class:`ResilientRunnable`。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        bound = llm.bind_tools([])
        assert isinstance(bound, ResilientRunnable)
        assert isinstance(bound, BaseChatModel)

    def test_with_retry_returns_resilient(self) -> None:
        """``llm.with_retry()`` 返回 :class:`ResilientRunnable`。"""
        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        wrapped = llm.with_retry()
        assert isinstance(wrapped, ResilientRunnable)

    def test_with_fallbacks_returns_resilient(self) -> None:
        """``llm.with_fallbacks([fb])`` 返回 :class:`ResilientRunnable`。"""
        from langchain_core.language_models.fake_chat_models import (
            FakeListChatModel,
        )

        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        fb = FakeListChatModel(responses=["fallback"])
        wrapped = llm.with_fallbacks([fb])
        assert isinstance(wrapped, ResilientRunnable)
        # 第一个 fallback 升格为 wrapper 自己的 _fallback
        assert wrapped.fallback is fb

    def test_with_structured_output_returns_resilient(self) -> None:
        """``llm.with_structured_output(Schema)`` 返回 :class:`ResilientRunnable`。"""
        from pydantic import BaseModel

        class Schema(BaseModel):
            x: int

        llm = get_llm(model_name="m", api_key="k", api_base="https://x")
        structured = llm.with_structured_output(Schema)
        assert isinstance(structured, ResilientRunnable)
        assert isinstance(structured, BaseChatModel)
