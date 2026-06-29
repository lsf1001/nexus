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


class TestBuildSystemPromptIsModelAware:
    """``_build_system_prompt`` 不再硬编码 model_name,改为引导 LLM 调 ``get_model_info`` 工具。

    WHY(2026-06-29 重构):
      之前的 fix 把 model_name 当字符串塞进 system prompt 模板(``f"基于 {driver_label} 打造"``)。
      这种"硬编码到 prompt"做法有几个固有问题:
        1. 模型切换若未走 ``POST /api/models/switch`` 重建 agent,prompt 还显示老模型 → 误导
        2. vendor / api_base / temperature 等其他元数据塞不进去(塞多了爆 LLM 上下文)
        3. 传不传 model_name 都能让 LLM 误答(传错值或瞎答训练记忆里的默认值)

      新契约:prompt 模板**不烘焙** model_name,改为强约束 LLM 调
      ``get_model_info`` 工具实时 introspect。模型身份变成"运行时事实"而非
      "字符串常量",切换模型后工具返回值立刻反映新状态 —— 这是用户反馈
      "应该真实获取模型的信息 而不是硬编码" 的根本修复。

    契约(2026-06-29 重构后):
      - ``_build_system_prompt`` 接受 ``model_name`` 参数仅为向后兼容,**不**把
        它写进 prompt 内容(传啥都一样)。
      - prompt 必须显式指引 LLM 调 ``get_model_info`` 工具获取当前驱动模型
        (FACT 块 + 回答规则 2 + forbidden 三处冗余)。
      - 不传 model_name / 传空串 → 走兼容路径,不抛(防御性,不阻塞启动)。
    """

    def test_prompt_does_not_hardcode_model_name(self) -> None:
        """prompt 字符串里不应该出现"当前驱动模型 = X"这种硬编码事实。"""
        prompt = _build_system_prompt("agnes-2.0-flash")
        # 重构后:无论传什么 model_name,prompt 里都不应该出现具体模型名作为
        # "驱动模型" 事实陈述(应该只出现 "调 get_model_info 拿值" 的指引)。
        assert "agnes-2.0-flash" not in prompt, (
            "_build_system_prompt(model_name) 还在把 model_name 硬编码到 prompt → "
            "这是 2026-06-29 重构要根除的'硬编码'做法。prompt 应当只引导 LLM 调 "
            "get_model_info 工具,模型身份应当是运行时事实。"
        )
        assert "MiniMax-M3" not in prompt, (
            "prompt 里出现 MiniMax-M3 字面量 → 同上,模型名不应作为字符串常量出现在 prompt"
        )

    def test_prompt_directs_to_get_model_info_tool(self) -> None:
        """prompt 必须显式指引 LLM 调 ``get_model_info`` 工具。"""
        prompt = _build_system_prompt()
        # FACT 块 + 回答规则 2 + forbidden 至少得有一处提到 get_model_info
        assert "get_model_info" in prompt, (
            "_build_system_prompt 漏掉 '调 get_model_info 工具' 指引 → "
            "LLM 不会主动 introspect,被问'你什么模型'时会瞎答训练记忆。"
        )
        # 强约束关键词:LLM 看到这些词才能理解"必须先调工具再答"
        assert "实时" in prompt or "运行时" in prompt, (
            "prompt 没强调模型身份是'运行时事实' → LLM 容易把 prompt 里的占位提示当成建议忽略"
        )

    def test_prompt_does_not_depend_on_model_name_param(self) -> None:
        """重构后,prompt 内容不应随 model_name 变化(避免无意义的契约面)。"""
        prompt_default = _build_system_prompt("")
        prompt_agnes = _build_system_prompt("agnes-2.0-flash")
        prompt_minimax = _build_system_prompt("MiniMax-M3")
        # 重构后:传啥都一样 — model_name 不再参与 prompt 模板拼接
        assert prompt_default == prompt_agnes == prompt_minimax, (
            "重构后 _build_system_prompt 应该不区分 model_name → "
            "三个不同 model_name 产出三个不同 prompt 说明仍在拼接字符串事实"
        )

    def test_other_rules_kept_when_model_name_provided(self) -> None:
        """重构后,其他规则段不能丢。"""
        prompt = _build_system_prompt("agnes-2.0-flash")
        assert "<thinking>" in prompt
        assert "【主动澄清规则】" in prompt
        assert "【安全规则】" in prompt
        # 产品身份段保留
        assert "夜小白科技有限公司" in prompt
        assert "Nexus" in prompt


class TestGetModelInfoToolRegistered:
    """``get_model_info`` 工具必须在 ``TOOLS`` 列表里注册,LLM 才能调到。

    WHY:2026-06-29 重构后,prompt 引导 LLM 调此工具 introspect 真实驱动模型。
    工具如果没注册到 TOOLS,deepagents 不会把它暴露给 LLM,prompt 指引形同虚设。
    """

    def test_get_model_info_in_tools(self) -> None:
        from nexus.backend.tools import TOOLS

        tool_names = {t.name for t in TOOLS}
        assert "get_model_info" in tool_names, (
            "get_model_info 工具未注册到 TOOLS → deepagents 不会把它暴露给 LLM,"
            "prompt 里的 '调 get_model_info' 指引形同虚设。"
        )

    def test_get_model_info_tool_returns_live_data(self, tmp_path, monkeypatch) -> None:
        """``get_model_info`` 工具调用应该实时读 ``~/.nexus/models.json``,返回 active 模型。"""
        import json

        from nexus.backend import models_config

        fake_models = {
            "models": [
                {
                    "id": "fake-minimax",
                    "name": "MiniMax-M3",
                    "api_key": "x",
                    "api_base": "https://api.minimaxi.com/v1",
                    "temperature": 0.7,
                    "is_active": False,
                },
                {
                    "id": "fake-agnes",
                    "name": "agnes-2.0-flash",
                    "api_key": "x",
                    "api_base": "https://apihub.agnes-ai.com/v1",
                    "temperature": 0.5,
                    "is_active": True,
                },
            ]
        }
        # 替换 models_config 的 MODELS_FILE 路径(只在本测试里)
        monkeypatch.setattr(models_config, "MODELS_FILE", tmp_path / "models.json")
        (tmp_path / "models.json").write_text(json.dumps(fake_models), encoding="utf-8")

        from nexus.backend.tools import get_model_info

        result = get_model_info.invoke({})
        payload = json.loads(result)
        # 工具必须返回 active 模型的真实信息(实时读盘,不读老 cache)
        assert payload["name"] == "agnes-2.0-flash"
        assert payload["vendor"] == "agnes-ai", (
            f"vendor 推断错误,期望 agnes-ai,实际 {payload['vendor']} → "
            "infer_vendor 解析 api_base 出错,LLM 答'哪个公司提供的'时会答错"
        )
        assert payload["api_base"] == "https://apihub.agnes-ai.com/v1"
        assert payload["temperature"] == 0.5

    def test_infer_vendor_minimax(self) -> None:
        from nexus.backend.models_config import infer_vendor

        assert infer_vendor({"api_base": "https://api.minimaxi.com/v1"}) == "MiniMax"
        assert infer_vendor({"api_base": "https://apihub.agnes-ai.com/v1"}) == "agnes-ai"
        assert infer_vendor({"api_base": "https://api.openai.com/v1"}) == "OpenAI"
        assert infer_vendor({"api_base": "https://api.anthropic.com/v1"}) == "Anthropic"
        # 未知 / 缺字段 → 走兜底,不抛
        assert infer_vendor({}) == "未知厂商"
        assert "未知厂商" in infer_vendor({"api_base": "https://example.com/v1"})


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

    def test_middleware_kwarg_does_not_duplicate_summarization(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
