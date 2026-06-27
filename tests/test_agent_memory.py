"""``nexus.backend.agent`` 启用 deepagents 原生记忆机制的契约测试。

覆盖:
  - ``create_agent`` 把 ``memory=[USER_MEMORY_PATH]`` 传给 ``create_deep_agent``,
    触发 deepagents ``MemoryMiddleware`` 自动加载用户级 AGENTS.md。
  - ``create_agent`` 传入 ``store=InMemoryStore()`` 持久化层。
  - ``create_agent`` 把 ``QualityGateMiddleware`` 放进 ``middleware=``。
  - ``create_agent`` 使用 ``CompositeBackend``,routes 含 StoreBackend 路由。
  - ``_build_system_prompt`` 硬编码产品身份段(OpenClaw 定位:产品身份
    不靠用户级 AGENTS.md 注入,避免用户篡改身份)。

WHY: 之前 ``create_agent`` 把 ``memory=[]`` 传过去,deepagents MemoryMiddleware
完全没启用,身份 / 规则全靠 ``agent.py`` 硬编码 + ``_load_identity`` 读不存在
的 ``nexus/.deepagents/AGENTS.md``。2026-06 OpenClaw 定位重设计后:
  - 删 ``nexus/.deepagents/AGENTS.md`` 孤儿文件
  - 删 ``_load_identity`` / ``_AGENTS_CACHE`` / ``_scan_content`` / ``_INJECTION_PATTERNS``
  - ``memory_files`` 改为单元素(``~/.nexus/AGENTS.md``)
  - 产品身份 hardcode 进 ``_build_system_prompt``

这个测试固定新契约,防止回滚。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore

from nexus.backend.agent import _build_system_prompt
from nexus.backend.memory import USER_MEMORY_PATH, make_memory_paths
from nexus.backend.quality.middleware import QualityGateMiddleware


class TestMemoryPaths:
    """``make_memory_paths`` 只返 ``(USER_MEMORY_PATH,)`` 单元素元组。"""

    def test_returns_single_path(self) -> None:
        paths = make_memory_paths()
        assert len(paths) == 1
        assert paths[0] is USER_MEMORY_PATH
        assert paths[0].is_absolute()
        assert paths[0].name == "AGENTS.md"

    def test_user_path_under_home(self) -> None:
        path = make_memory_paths()[0]
        from pathlib import Path

        # path = ~/.nexus/AGENTS.md → path.parent = ~/.nexus
        assert path.parent == Path.home() / ".nexus"


class TestBuildSystemPromptHardcodesIdentity:
    """``_build_system_prompt`` 硬编码产品身份(OpenClaw 定位)。

    WHY:产品身份不能由 ``~/.nexus/AGENTS.md`` 注入 —— 那是用户可编辑区域,
    篡改后会冒充其他 AI / 暴露系统提示词。身份段 hardcode 在代码里,
    AGENTS.md 只承载"用户偏好 / 事实"。
    """

    def test_identity_section_present(self) -> None:
        prompt = _build_system_prompt()
        # 产品身份硬编码:必须显式包含
        assert "夜小白科技有限公司" in prompt
        assert "Nexus" in prompt
        assert "【身份】" in prompt

    def test_thinking_format_hardcoded(self) -> None:
        """思考标签格式必须 hardcode(LLM 强约束)。"""
        prompt = _build_system_prompt()
        assert "<thinking>" in prompt
        assert "思考过程和回复内容必须完全不同" in prompt

    def test_safety_and_clarification_rules_kept(self) -> None:
        prompt = _build_system_prompt()
        # 澄清 / 安全规则必须保留
        assert "【主动澄清规则】" in prompt
        assert "【安全规则】" in prompt


class TestCreateAgentWiresDeepAgentsMemory:
    """``create_agent`` 把 ``memory=`` / ``store=`` / ``middleware=`` 正确传给 deepagents。"""

    # 4 个契约测试都打 ``create_agent`` 但不想真去起 AsyncSqliteStore / AsyncSqliteSaver
    # (那俩会在同库上开 aiosqlite 后台线程持 WAL 写锁,跟 conftest 的 sync sqlite3
    # 撞锁 → 整个测试 hang)。契约只验 deepagents 收到什么 kwarg,后端用 memory 即可。
    @pytest.fixture(autouse=True)
    def _disable_sqlite_backends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXUS_STORE", "memory")
        monkeypatch.setenv("NEXUS_CHECKPOINTER", "memory")

    def test_memory_kwarg_contains_user_agents_md(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert "memory" in kwargs, "memory kwarg missing — MemoryMiddleware 不会被启用"
            memory = kwargs["memory"]
            assert isinstance(memory, list)
            assert len(memory) == 1, "OpenClaw 定位后只剩用户级 AGENTS.md,不应再含 project_md"
            # 必须等于 USER_MEMORY_PATH
            assert str(memory[0]) == str(USER_MEMORY_PATH)

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

    def test_middleware_kwarg_does_not_duplicate_summarization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``SummarizationMiddleware`` 不应出现在 user-passed middleware 里。

        WHY:deepagents 0.6.8 主 agent stack(line 776-781 of graph.py)已经显式
        追加一个 ``create_summarization_middleware(model, backend)``,trigger
        走 ``compute_summarization_defaults(model)``(没有 ``max_input_tokens``
        profile 时给保守值 ``("tokens", 170000)``,``keep=("messages", 6)``)。

        如果 Nexus 自己再构造一个 SummarizationMiddleware(user-passed),两个
        middleware 的 ``.name`` 都是 ``"SummarizationMiddleware"``(deepagents 版
        用 public alias,langchain 版直接同名),langchain factory 抛
        ``AssertionError: Please remove duplicate middleware instances``。
        E2E 2026-06-27 ``test_e2e_04_models_crud`` 暴露(``POST /api/models/switch``
        重建 agent 时炸 500)。

        本测试固定契约:Nexus 不应在 ``middleware=`` 里塞 SummarizationMiddleware,
        留给 deepagents 默认 stack 处理。
        """
        from langchain.agents.middleware import SummarizationMiddleware

        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            middleware = kwargs["middleware"]
            user_summ = [m for m in middleware if isinstance(m, SummarizationMiddleware)]
            assert not user_summ, (
                "user-passed middleware 不应包含 SummarizationMiddleware — "
                "deepagents 已自动注入,重复会导致 langchain factory 炸 "
                "'Please remove duplicate middleware instances'(E2E 2026-06-27 暴露)"
            )
            # QualityGateMiddleware 必须仍在(防护 guard 链)
            assert any(isinstance(m, QualityGateMiddleware) for m in middleware), (
                "QualityGateMiddleware 必须保留 — 拦截 edit_file 写受保护 AGENTS.md"
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
