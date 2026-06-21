"""``nexus.backend.agent`` 启用 deepagents 原生记忆机制的契约测试。

覆盖:
  - ``create_agent`` 把 ``memory=[user_md, project_md]`` 传给 ``create_deep_agent``,
    触发 deepagents ``MemoryMiddleware`` 自动加载 AGENTS.md。
  - ``create_agent`` 传入 ``store=InMemoryStore()`` 持久化层。
  - ``create_agent`` 把 ``QualityGateMiddleware`` 放进 ``middleware=``。
  - ``create_agent`` 使用 ``CompositeBackend``,routes 含 StoreBackend 路由。
  - ``_build_system_prompt`` 不再硬编码身份段（身份由 MemoryMiddleware 注入）。

WHY: 之前 ``create_agent`` 把 ``memory=[]`` 传过去,deepagents MemoryMiddleware
完全没启用,身份 / 规则全靠 ``agent.py`` 硬编码 + ``_load_identity`` 读不存在
的 ``nexus/.nexus/AGENTS.md``。这个测试固定新契约,防止回滚。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore

from nexus.backend.agent import _build_system_prompt
from nexus.backend.memory import make_memory_paths
from nexus.backend.quality.middleware import QualityGateMiddleware


class TestMemoryPaths:
    """``make_memory_paths`` 返回 ``(user_md, project_md)``."""

    def test_returns_two_paths(self) -> None:
        user, project = make_memory_paths()
        assert user.is_absolute()
        assert project.is_absolute()
        assert user.name == "AGENTS.md"
        assert project.name == "AGENTS.md"

    def test_user_path_under_home(self) -> None:
        user, _ = make_memory_paths()
        from pathlib import Path

        # user = ~/.deepagents/AGENTS.md → user.parent = ~/.deepagents
        assert user.parent == Path.home() / ".deepagents"

    def test_project_path_under_repo(self) -> None:
        _, project = make_memory_paths()
        # 必须落在 nexus/.deepagents/ 下,而不是历史路径 nexus/.nexus/
        assert project.parent.name == ".deepagents"
        assert project.parent.parent.name == "nexus"


class TestBuildSystemPromptSlim:
    """``_build_system_prompt`` 不再硬编码身份(由 AGENTS.md 注入)。"""

    def test_no_hardcoded_identity(self) -> None:
        prompt = _build_system_prompt()
        # 身份段被删,只剩安全 / 澄清规则
        assert "夜小白科技有限公司" not in prompt
        assert "你是 Nexus" not in prompt or "【主动澄清规则】" in prompt  # 澄清规则仍提及
        # 澄清 / 安全规则必须保留
        assert "【主动澄清规则】" in prompt
        assert "【安全规则】" in prompt


class TestCreateAgentWiresDeepAgentsMemory:
    """``create_agent`` 把 ``memory=`` / ``store=`` / ``middleware=`` 正确传给 deepagents。"""

    def test_memory_kwarg_contains_agents_md_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert "memory" in kwargs, "memory kwarg missing — MemoryMiddleware 不会被启用"
            memory = kwargs["memory"]
            assert isinstance(memory, list)
            assert len(memory) >= 2, "至少包含 user_md + project_md"
            # 必须是 deepagents 0.6.8 约定的路径(项目级 + 用户级)
            user_md, project_md = make_memory_paths()
            assert str(project_md) in [str(p) for p in memory]
            assert str(user_md) in [str(p) for p in memory]

    def test_store_kwarg_is_in_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert "store" in kwargs, "store kwarg missing — 长期偏好无法持久化"
            assert isinstance(kwargs["store"], InMemoryStore)

    def test_middleware_kwarg_contains_quality_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert "middleware" in kwargs
            middleware = kwargs["middleware"]
            assert any(isinstance(m, QualityGateMiddleware) for m in middleware), (
                "QualityGateMiddleware 必须装到 middleware 里拦截 edit_file"
            )

    def test_backend_is_composite_with_store_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from deepagents.backends.composite import CompositeBackend

        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            backend = kwargs["backend"]
            assert isinstance(backend, CompositeBackend), "backend 必须是 CompositeBackend,内置工具才能读写多个文件系统"
            # 必须有 StoreBackend 路由(/memories/ 是 deepagents 推荐约定)
            assert any("/memories/" in str(prefix) for prefix in backend.routes), (
                f"routes 缺少 /memories/: {list(backend.routes)}"
            )
