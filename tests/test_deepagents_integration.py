"""DeepAgents 0.6.8 模块集成测试。

覆盖:
  - ``_create_store``:memory / sqlite 两路 + 异常降级
  - ``_select_filesystem_backend``:默认 / NEXUS_ENABLE_EXEC=1 / 缺参报错
  - ``profiles.register_nexus_profiles``:幂等 + register 后可读到
  - ``_load_async_subagent_specs``:空 / 坏 JSON / 缺字段
  - ``_load_compiled_subagent_specs``:空 / 坏 JSON / module 不存在 / 缺字段 / 正常加载

WHY 单测而非 e2e:每个 helper 都很纯(env → 对象),e2e 路径都覆盖过;
单测更细粒度、出错信息更直接。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus.backend import agent as agent_module
from nexus.backend import profiles as profiles_module
from nexus.backend.profiles import (
    register_nexus_profiles,
    reset_profiles_for_test,
)


# ============================================================================
# _create_store
# ============================================================================
class TestCreateStore:
    """验证 NEXUS_STORE env 选 memory / sqlite + 异常路径。"""

    def test_default_is_sqlite(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """默认 → AsyncSqliteStore。

        WHY monkeypatch Path.home:_create_store 默认走
        ``Path.home() / ".nexus" / "nexus.db"``,在 tmp_path 隔离下要
        强行把"home"指到 tmp_path,避免写真实用户目录 + 跨 case 锁库。
        """
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("NEXUS_STORE", raising=False)
        store = agent_module._create_store()
        # AsyncSqliteStore 是 langgraph.checkpoint.sqlite.aio 的具体类
        # → 名字含 "Sqlite" 且 aio 标志
        assert "Sqlite" in type(store).__name__
        # 默认行为不能跟 InMemoryStore 撞名(防止 import 错误时退化)
        assert "Memory" not in type(store).__name__
        # store 持有了 aiosqlite 连接,挂到 atexit;但 case 退出时想尽快关
        # 连接避免线程挂死。简单做法:找到 conn 调 close(异步)。
        if hasattr(store, "conn"):
            import asyncio

            asyncio.run(store.conn.close())  # type: ignore[attr-defined]

    def test_memory_backend_uses_in_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """NEXUS_STORE=memory → InMemoryStore(in-process,单测用)。"""
        monkeypatch.setenv("NEXUS_STORE", "memory")
        store = agent_module._create_store()
        # InMemoryStore 来自 langgraph.store.memory,类名固定
        assert "Memory" in type(store).__name__

    def test_store_is_reused_until_runtime_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同一配置反复构造 Agent 时必须复用 Store，避免连接与状态泄漏。"""
        monkeypatch.setenv("NEXUS_STORE", "memory")

        first_store = agent_module._create_store()
        second_store = agent_module._create_store()

        assert second_store is first_store

    def test_runtime_reset_closes_cached_store(self) -> None:
        """统一重置必须显式关闭 Store 连接，不能依赖进程退出钩子。"""
        closed_keys: list[str] = []
        agent_module._STORE_CACHE["fake"] = (object(), lambda: closed_keys.append("fake"))

        agent_module._reset_checkpointer_cache()

        assert closed_keys == ["fake"]
        assert not agent_module._STORE_CACHE


# ============================================================================
# _select_filesystem_backend
# ============================================================================
class TestSelectFilesystemBackend:
    """验证 execution backend 选型:默认 / LocalShell / LangSmith / ContextHub。"""

    def test_default_is_filesystem(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """无 env → FilesystemBackend(无 execute 工具)。"""
        monkeypatch.delenv("NEXUS_ENABLE_EXEC", raising=False)
        monkeypatch.delenv("NEXUS_EXEC_BACKEND", raising=False)
        backend = agent_module._select_filesystem_backend(tmp_path)
        assert type(backend).__name__ == "FilesystemBackend"

    def test_local_shell_via_enable_exec(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """NEXUS_ENABLE_EXEC=1 → LocalShellBackend(本地 execute)。"""
        monkeypatch.setenv("NEXUS_ENABLE_EXEC", "1")
        monkeypatch.delenv("NEXUS_EXEC_BACKEND", raising=False)
        backend = agent_module._select_filesystem_backend(tmp_path)
        assert type(backend).__name__ == "LocalShellBackend"

    def test_langsmith_requires_sandbox_name(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """NEXUS_EXEC_BACKEND=langsmith 但没配沙箱名 → 抛 ValueError。"""
        monkeypatch.setenv("NEXUS_EXEC_BACKEND", "langsmith")
        monkeypatch.delenv("NEXUS_LANGSMITH_SANDBOX_NAME", raising=False)
        with pytest.raises(ValueError, match="NEXUS_LANGSMITH_SANDBOX_NAME"):
            agent_module._select_filesystem_backend(tmp_path)

    def test_context_hub_requires_identifier(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """NEXUS_EXEC_BACKEND=context_hub 但没配 hub id → 抛 ValueError。"""
        monkeypatch.setenv("NEXUS_EXEC_BACKEND", "context_hub")
        monkeypatch.delenv("NEXUS_CONTEXT_HUB_ID", raising=False)
        with pytest.raises(ValueError, match="NEXUS_CONTEXT_HUB_ID"):
            agent_module._select_filesystem_backend(tmp_path)


# ============================================================================
# profiles
# ============================================================================
class TestProfiles:
    """ProviderProfile / HarnessProfile 注册幂等。"""

    def setup_method(self) -> None:
        """每个 case 前重置,避免上一 case 残留 _PROFILES_REGISTERED=True。"""
        reset_profiles_for_test()

    def teardown_method(self) -> None:
        reset_profiles_for_test()

    def test_register_is_idempotent(self) -> None:
        """连续调两次 register_nexus_profiles 不会炸,第二次走早退路径。"""
        # WHY 用 ``profiles_module._PROFILES_REGISTERED`` 而不是 ``from import``:
        # ``from profiles import _PROFILES_REGISTERED`` 是值复制,函数内
        # ``global _PROFILES_REGISTERED = True`` 改的是模块全局,本地 copy
        # 看不到(True trap)。始终通过模块属性读,看到的是同一份内存。
        register_nexus_profiles()
        assert profiles_module._PROFILES_REGISTERED is True
        # 第二次:已注册标志 → 早退,不重新走 register_provider_profile
        # (如果重复注册会触发 deepagents 内部的 key 已存在警告)
        register_nexus_profiles()
        assert profiles_module._PROFILES_REGISTERED is True

    def test_harness_profile_field_set_matches_deepagents_0_6_12(self) -> None:
        """HarnessProfile 字段集合 == 0.6.12 真实签名。

        WHY:0.6.x 之间字段集可能变化(excluded_tools / excluded_middleware /
        extra_middleware 在 0.6 中期才加)。一旦 deepagents 升 0.7,Nexus 必须
        重新对照。这个 case 是版本基线,任何字段增删都让 case RED 提醒。
        """
        import inspect

        from deepagents.profiles.harness.harness_profiles import HarnessProfile

        actual = set(inspect.signature(HarnessProfile.__init__).parameters)
        # 7 字段 + self,扣除 self
        actual.discard("self")
        expected = {
            "base_system_prompt",
            "system_prompt_suffix",
            "tool_description_overrides",
            "excluded_tools",
            "excluded_middleware",
            "extra_middleware",
            "general_purpose_subagent",
        }
        assert actual == expected, (
            f"deepagents 0.6.12 HarnessProfile 字段集漂移:actual={sorted(actual)}, "
            f"expected={sorted(expected)}"
        )

    def test_general_purpose_subagent_field_set_matches_0_6_12(self) -> None:
        """GeneralPurposeSubagentProfile 字段集合 == 0.6.12 真实签名。"""
        import inspect

        from deepagents.profiles.harness.harness_profiles import GeneralPurposeSubagentProfile

        actual = set(inspect.signature(GeneralPurposeSubagentProfile.__init__).parameters)
        actual.discard("self")
        expected = {"enabled", "description", "system_prompt"}
        assert actual == expected, (
            f"GeneralPurposeSubagentProfile 字段漂移:actual={sorted(actual)}, "
            f"expected={sorted(expected)}"
        )

    def test_create_deep_agent_signature_0_6_12(self) -> None:
        """create_deep_agent 参数集合 == 0.6.12 真实签名(基线)。"""
        import inspect

        from deepagents.graph import create_deep_agent

        actual = set(inspect.signature(create_deep_agent).parameters)
        actual.discard("self")
        expected = {
            "model",
            "tools",
            "system_prompt",
            "middleware",
            "subagents",
            "skills",
            "memory",
            "permissions",
            "backend",
            "interrupt_on",
            "response_format",
            "state_schema",
            "context_schema",
            "checkpointer",
            "store",
            "debug",
            "name",
            "cache",
        }
        assert actual == expected, (
            f"create_deep_agent 参数集漂移:actual={sorted(actual)}, "
            f"expected={sorted(expected)}\ndiff: actual-only={sorted(actual - expected)}, "
            f"expected-only={sorted(expected - actual)}"
        )

    def test_subagent_typeddict_required_keys_0_6_12(self) -> None:
        """SubAgent / CompiledSubAgent / AsyncSubAgent TypedDict required == 0.6.12。

        这是 2026-08-04 对齐报告 §3/§4 的事实基线:required 字段决定启动期
        是否需要校验。``AsyncSubAgent`` 把 ``url`` 从 required 降级为
        optional 是 0.6.12 的事实(报告 §7 TODO 1 的依据)。
        """
        from deepagents.middleware.async_subagents import AsyncSubAgent
        from deepagents.middleware.subagents import CompiledSubAgent, SubAgent

        assert set(SubAgent.__required_keys__) == {"name", "description", "system_prompt"}
        assert set(CompiledSubAgent.__required_keys__) == {"name", "description", "runnable"}
        assert set(AsyncSubAgent.__required_keys__) == {"name", "description", "graph_id"}
        # url 在 0.6.12 降级为 optional(报告 §7 TODO 1)
        assert "url" not in set(AsyncSubAgent.__required_keys__)
        assert "url" in set(AsyncSubAgent.__optional_keys__)


# ============================================================================
# _load_async_subagent_specs
# ============================================================================
class TestLoadAsyncSubagentSpecs:
    """AsyncSubAgent JSON env loader 的三类路径:正常 / 坏 JSON / 缺字段。"""

    def test_empty_env_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设 env → 空列表(不启用 AsyncSubAgent)。"""
        monkeypatch.delenv("NEXUS_ASYNC_SUBAGENTS_JSON", raising=False)
        assert agent_module._load_async_subagent_specs() == []

    def test_bad_json_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """解析失败 → 空列表 + warning(不让坏配置炸启动)。"""
        monkeypatch.setenv("NEXUS_ASYNC_SUBAGENTS_JSON", "not valid json {")
        assert agent_module._load_async_subagent_specs() == []

    def test_non_list_json_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON 不是数组 → 空列表 + warning。"""
        monkeypatch.setenv("NEXUS_ASYNC_SUBAGENTS_JSON", '{"name":"x","description":"y"}')
        assert agent_module._load_async_subagent_specs() == []

    def test_missing_required_fields_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺 name/description/graph_id → 跳过该条 + warning。

        0.6.12 ``AsyncSubAgent`` TypedDict required={name, description, graph_id},
        ``graph_id`` 是 LangGraph 平台 deployment_id,缺了首次调用才炸(延迟到
        运行期)。Nexus 在加载期就拒,启动期失败 = 启动期可观测。
        """
        monkeypatch.setenv(
            "NEXUS_ASYNC_SUBAGENTS_JSON",
            '[{"name":"x"},{"description":"y"},{"name":"a","description":"b"}]',
        )
        assert agent_module._load_async_subagent_specs() == []

    def test_valid_specs_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """完整 spec → 返回 AsyncSubAgent TypedDict。

        0.6.12 ``AsyncSubAgent``:required={name, description, graph_id},
        optional={url, headers}。url 缺省时框架走 LangGraph Platform 默认地址。
        """
        monkeypatch.setenv(
            "NEXUS_ASYNC_SUBAGENTS_JSON",
            '[{"name":"remote_writer","description":"远程写作",'
            '"graph_id":"deploy-123","url":"https://x.example"}]',
        )
        specs = agent_module._load_async_subagent_specs()
        assert len(specs) == 1
        assert specs[0]["name"] == "remote_writer"
        assert specs[0]["url"] == "https://x.example"
        assert specs[0]["graph_id"] == "deploy-123"

    def test_url_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """url 缺省仍可解析(0.6.12 url 是 optional)。"""
        monkeypatch.setenv(
            "NEXUS_ASYNC_SUBAGENTS_JSON",
            '[{"name":"r","description":"d","graph_id":"g1"}]',
        )
        specs = agent_module._load_async_subagent_specs()
        assert len(specs) == 1
        assert "url" not in specs[0]


# ============================================================================
# _load_compiled_subagent_specs
# ============================================================================
class TestLoadCompiledSubagentSpecs:
    """CompiledSubAgent JSON env loader:动态 import factory,失败跳过该条。"""

    def test_empty_env_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设 env → 空列表(默认不挂用户子图)。"""
        monkeypatch.delenv("NEXUS_COMPILED_SUBAGENTS_JSON", raising=False)
        assert agent_module._load_compiled_subagent_specs() == []

    def test_bad_json_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """坏 JSON → 空列表 + warning。"""
        monkeypatch.setenv("NEXUS_COMPILED_SUBAGENTS_JSON", "{not json")
        assert agent_module._load_compiled_subagent_specs() == []

    def test_missing_fields_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺 name/description/module_path/factory 任何一个 → 跳过。"""
        monkeypatch.setenv(
            "NEXUS_COMPILED_SUBAGENTS_JSON",
            '[{"name":"x"},{"description":"y","module_path":"m","factory":"f"}]',
        )
        assert agent_module._load_compiled_subagent_specs() == []

    def test_nonexistent_module_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """module_path 找不到 → 跳过 + warning(不让 import 错炸启动)。"""
        monkeypatch.setenv(
            "NEXUS_COMPILED_SUBAGENTS_JSON",
            '[{"name":"x","description":"y","module_path":"definitely_not_a_real_module_xyz","factory":"build_agent"}]',
        )
        assert agent_module._load_compiled_subagent_specs() == []

    def test_valid_factory_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """完整 spec → 动态 import + 调 factory,拿到 runnable。"""
        import importlib

        # 直接复用 nexus.backend.profiles 里的模块作 demo target
        # (该模块有现成的 register_nexus_profiles 可调用)
        # 工厂需要返回 Runnable — 用 MagicMock 代替
        fake_runnable = MagicMock()
        fake_module = MagicMock()
        fake_module.build_agent = MagicMock(return_value=fake_runnable)  # type: ignore[attr-defined]

        def fake_import_module(path: str) -> Any:
            if path == "nexus.backend.profiles":
                return fake_module
            raise ImportError(path)

        monkeypatch.setattr(importlib, "import_module", fake_import_module)
        monkeypatch.setenv(
            "NEXUS_COMPILED_SUBAGENTS_JSON",
            '[{"name":"custom","description":"自定义","module_path":"nexus.backend.profiles","factory":"build_agent"}]',
        )
        specs = agent_module._load_compiled_subagent_specs()
        assert len(specs) == 1
        assert specs[0]["name"] == "custom"
        assert specs[0]["runnable"] is fake_runnable
        fake_module.build_agent.assert_called_once()  # factory() 必须无参调一次
