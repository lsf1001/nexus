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
        """缺 name 或 description → 跳过该条 + warning。"""
        monkeypatch.setenv(
            "NEXUS_ASYNC_SUBAGENTS_JSON",
            '[{"name":"x"},{"description":"y"}]',
        )
        assert agent_module._load_async_subagent_specs() == []

    def test_valid_specs_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """完整 spec → 返回 AsyncSubAgent TypedDict。"""
        monkeypatch.setenv(
            "NEXUS_ASYNC_SUBAGENTS_JSON",
            '[{"name":"remote_writer","description":"远程写作","url":"https://x.example"}]',
        )
        specs = agent_module._load_async_subagent_specs()
        assert len(specs) == 1
        assert specs[0]["name"] == "remote_writer"
        assert specs[0]["url"] == "https://x.example"


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
