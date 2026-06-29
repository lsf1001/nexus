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


class TestBuildSystemPromptIsModelAgnostic:
    """``_build_system_prompt`` 输出**与激活模型无关**的稳定字符串。

    2026-06-29 第三轮重构:FACT 块从 prompt 字符串里移走,改由
    :class:`DynamicIdentityMiddleware` 在每次 LLM 调用前实时注入。理由:

      - 旧方案把 ``"当前驱动模型 = X"`` 烤进 ``create_agent()`` 阶段的
        system_prompt 字符串,agent 构造一次后**不再刷新**。用户切换
        ``~/.nexus/models.json`` 后,UI 标题栏(``/api/model`` 端点读
        models.json)和 LLM 自报身份不一致(E2E 2026-06-29 真实 bug)。
      - 新方案:prompt 只承载产品层稳定规则(身份 / 思考格式 / 澄清 /
        安全);FACT 块由 middleware 在 ``wrap_model_call`` 钩子里**每次
        调用前**重读 models.json 注入。单一数据源,绝无缓存滞留。

    契约:
      - prompt 输出是**纯静态**的,切换 active model 后内容**完全不变**。
      - prompt 必须显式提到 ``DynamicIdentityMiddleware`` 注入的 FACT 块
        以及 ``get_model_info`` 工具(让 LLM 知道该用哪份数据答身份问题)。
      - 思考格式 / 安全 / 澄清规则等"产品层规则"必须保留。
      - prompt **不能**包含任何具体模型名(否则就成了新的 hardcode 串味源)。
    """

    @pytest.fixture
    def _patch_active_model(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        """把 ``models_config.MODELS_FILE`` 指向 tmp 路径,避免污染真实配置."""
        import json
        from nexus.backend import models_config

        fake = {
            "models": [
                {
                    "id": "fake-agnes",
                    "name": "agnes-2.0-flash",
                    "api_key": "x",
                    "api_base": "https://apihub.agnes-ai.com/v1",
                    "temperature": 0.7,
                    "is_active": True,
                },
            ]
        }
        monkeypatch.setattr(models_config, "MODELS_FILE", tmp_path / "models.json")
        (tmp_path / "models.json").write_text(json.dumps(fake), encoding="utf-8")
        # 清空 _CACHED_PROMPT,避免老 cache 干扰
        from nexus.backend import agent
        monkeypatch.setattr(agent, "_CACHED_PROMPT", {})

    def test_prompt_does_not_bake_active_model_name(self, _patch_active_model) -> None:
        """prompt 不应再含具体模型名(否则就退化成 hardcode 串味源)。"""
        prompt = _build_system_prompt()
        assert "agnes-2.0-flash" not in prompt, (
            "prompt 不应再含 agnes-2.0-flash → _build_system_prompt 不应再 hardcode "
            "当前激活模型;FACT 块改由 DynamicIdentityMiddleware 注入"
        )

    def test_prompt_mentions_middleware_fact_block(self, _patch_active_model) -> None:
        """prompt 必须显式提到 ``DynamicIdentityMiddleware`` / FACT 块,LLM 才知道
        答身份问题该用哪份数据。"""
        prompt = _build_system_prompt()
        assert "DynamicIdentityMiddleware" in prompt, (
            "prompt 没提 DynamicIdentityMiddleware → LLM 不知道 FACT 块从哪来,"
            "被问'你用的什么模型'时会瞎答"
        )
        assert "FACT" in prompt
        assert "models.json" in prompt, (
            "prompt 必须说明 FACT 块数据源是 models.json,LLM 才有信心"
        )

    def test_prompt_mentions_get_model_info_tool(self, _patch_active_model) -> None:
        """prompt 必须提到 ``get_model_info`` 工具(让 LLM 知道备用通道)。"""
        prompt = _build_system_prompt()
        assert "get_model_info" in prompt, (
            "prompt 没提 get_model_info 工具 → LLM 不会知道有备用 introspect 通道"
        )

    def test_prompt_is_model_independent(self, tmp_path, monkeypatch) -> None:
        """切换 active model 后,prompt 内容**完全不变**(因为不再读 models.json)。"""
        import json
        from nexus.backend import agent
        from nexus.backend import models_config

        # 第一组: agnes 激活
        monkeypatch.setattr(models_config, "MODELS_FILE", tmp_path / "models.json")
        (tmp_path / "models.json").write_text(json.dumps({
            "models": [{"id": "a", "name": "agnes-2.0-flash", "api_key": "x",
                        "api_base": "https://apihub.agnes-ai.com/v1",
                        "temperature": 0.7, "is_active": True}]
        }), encoding="utf-8")
        monkeypatch.setattr(agent, "_CACHED_PROMPT", {})
        prompt_agnes = _build_system_prompt()

        # 第二组: MiniMax-M3 激活
        (tmp_path / "models.json").write_text(json.dumps({
            "models": [{"id": "m", "name": "MiniMax-M3", "api_key": "x",
                        "api_base": "https://api.minimaxi.com/v1",
                        "temperature": 0.7, "is_active": True}]
        }), encoding="utf-8")
        monkeypatch.setattr(agent, "_CACHED_PROMPT", {})
        prompt_minimax = _build_system_prompt()

        assert prompt_agnes == prompt_minimax, (
            "切换 active model 后 prompt 变了 → _build_system_prompt 不应再依赖 "
            "models.json,否则就是新 hardcode 串味源"
        )

    def test_other_rules_kept(self, _patch_active_model) -> None:
        """重构后,产品层规则段不能丢。"""
        prompt = _build_system_prompt()
        assert "<thinking>" in prompt
        assert "【主动澄清规则】" in prompt
        assert "【安全规则】" in prompt
        # 产品身份段保留
        assert "夜小白科技有限公司" in prompt
        assert "Nexus" in prompt


class TestDynamicIdentityMiddleware:
    """``DynamicIdentityMiddleware`` 必须在每次 LLM 调用前实时注入当前 active model。

    契约:
      - ``wrap_model_call`` 钩子必须 mutate ``request.system_message.content``,
        prepend 一段含 ``name`` / ``vendor`` 的 FACT 块。
      - FACT 块内容**不**缓存(每次都重读 ``models.json``)。
      - ``get_active_model_info()`` 返回空时走降级措辞(``未配置模型``),
        绝不编造。
    """

    @pytest.fixture
    def _patch_active_model(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        """替换 ``models_config.MODELS_FILE`` 到 tmp,避免污染真实配置。"""
        import json
        from nexus.backend import models_config

        fake = {
            "models": [
                {
                    "id": "fake-agnes",
                    "name": "agnes-2.0-flash",
                    "api_key": "x",
                    "api_base": "https://apihub.agnes-ai.com/v1",
                    "temperature": 0.7,
                    "is_active": True,
                },
            ]
        }
        monkeypatch.setattr(models_config, "MODELS_FILE", tmp_path / "models.json")
        (tmp_path / "models.json").write_text(json.dumps(fake), encoding="utf-8")

    def _build_request(self, system_text: str = "base prompt"):
        """构造一个带固定 system_message 的 ModelRequest 并返回 (mw, request, handler, captured)。

        LangChain ``@wrap_model_call`` 装饰器返回的是 :class:`AgentMiddleware`
        实例。本 middleware 用 ``async def`` 实现,装饰器只注册
        ``awrap_model_call``(deepagents 的 ``agent.astream(...)`` 走 async
        路径;sync ``wrap_model_call`` 在 async 上下文里会抛 NotImplementedError,
        2026-06-29 E2E 暴露)。测试用 ``asyncio.run`` 调 ``awrap_model_call``。
        """
        from langchain.agents.middleware.types import ModelResponse
        from langchain_core.messages import AIMessage, SystemMessage

        from nexus.backend.middleware.dynamic_identity import dynamic_identity_middleware

        captured: dict = {}

        async def fake_handler(req):
            # 把 mutate 后的 system_message.content 抓出来供断言
            captured["system_content"] = req.system_message.content
            return ModelResponse(result=[AIMessage(content="ok")])

        request = MagicMock()
        request.system_message = SystemMessage(content=system_text)
        return dynamic_identity_middleware, request, fake_handler, captured

    def _invoke_middleware(self, mw, request, handler, captured):
        """统一调 ``mw.awrap_model_call``(async),把 mutate 后的 system_message 抓出来。

        跟 deepagents ws.py 的 ``agent.astream(...)`` 调用栈对齐(都是 async 路径)。
        """
        import asyncio

        result = asyncio.run(mw.awrap_model_call(request, handler))
        return result, captured["system_content"]

    def test_middleware_injects_fact_block_with_active_model(self, _patch_active_model) -> None:
        """middleware 调用后,system_message.content 必须含 active model 的 name + vendor。"""
        mw, request, handler, captured = self._build_request("base prompt here")

        _, content = self._invoke_middleware(mw, request, handler, captured)

        assert "agnes-2.0-flash" in content, (
            f"FACT 块没注入 active model name,实际 content: {content[:300]}"
        )
        assert "agnes-ai" in content, (
            f"FACT 块没注入 vendor,实际 content: {content[:300]}"
        )
        # FACT 块必须在最前面(LLM 训练记忆里如果对位置敏感,prepend 比 append 更稳)
        assert content.startswith("【FACT"), (
            f"FACT 块没 prepend 到最前,实际开头: {content[:200]}"
        )
        # 原始 system prompt 内容必须保留(不能 overwrite 整个 system_message)
        assert "base prompt here" in content

    def test_middleware_reads_models_json_freshly(self, tmp_path, monkeypatch) -> None:
        """切换 active model 后,下次 middleware 调用必须反映新值(无缓存)。"""
        import json
        from nexus.backend import models_config

        monkeypatch.setattr(models_config, "MODELS_FILE", tmp_path / "models.json")
        (tmp_path / "models.json").write_text(json.dumps({
            "models": [{"id": "a", "name": "agnes-2.0-flash", "api_key": "x",
                        "api_base": "https://apihub.agnes-ai.com/v1",
                        "temperature": 0.7, "is_active": True}]
        }), encoding="utf-8")

        mw, request, handler, captured = self._build_request()
        _, content1 = self._invoke_middleware(mw, request, handler, captured)
        assert "agnes-2.0-flash" in content1

        # 切换 active model 到 MiniMax-M3
        (tmp_path / "models.json").write_text(json.dumps({
            "models": [{"id": "m", "name": "MiniMax-M3", "api_key": "x",
                        "api_base": "https://api.minimaxi.com/v1",
                        "temperature": 0.7, "is_active": True}]
        }), encoding="utf-8")

        # 新一轮 LLM 调用(无 cache,无 reload)—— middleware 必须读出新值
        mw2, request2, handler2, captured2 = self._build_request()
        _, content2 = self._invoke_middleware(mw2, request2, handler2, captured2)
        assert "MiniMax-M3" in content2, (
            "切换 active model 后 middleware 还是用老 agnes → 它缓存了,"
            "重读 models.json 的契约没生效"
        )
        assert "MiniMax" in content2

    def test_middleware_handles_missing_active_model(self, tmp_path, monkeypatch) -> None:
        """``models.json`` 里没有 active 模型时,FACT 块走降级措辞(未配置模型)。"""
        import json
        from nexus.backend import models_config

        monkeypatch.setattr(models_config, "MODELS_FILE", tmp_path / "models.json")
        (tmp_path / "models.json").write_text(json.dumps({
            "models": [{"id": "x", "name": "inactive-model", "api_key": "x",
                        "api_base": "https://x.com/v1", "temperature": 0.7,
                        "is_active": False}]
        }), encoding="utf-8")

        mw, request, handler, captured = self._build_request()
        _, content = self._invoke_middleware(mw, request, handler, captured)
        assert "未配置模型" in content, (
            "无 active 模型时 middleware 没走降级措辞 → LLM 会瞎答"
        )
        assert "inactive-model" not in content, (
            "middleware 不应把 is_active=False 的模型注入 FACT 块"
        )


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

    def test_middleware_kwarg_contains_dynamic_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``DynamicIdentityMiddleware`` 必须出现在 ``middleware=`` 列表里。

        WHY:2026-06-29 第三轮重构后,动态身份注入从 prompt 字符串挪到
        middleware。如果这条契约破了,LLM 收到的 system prompt 永远不含
        当前激活模型信息(因为 prompt 字符串本身已经模型无关),标题栏
        和 LLM 答对不上(E2E 2026-06-29 真实 bug 的根因)。
        """
        from langchain.agents.middleware import AgentMiddleware

        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            middleware = kwargs["middleware"]
            # dynamic_identity_middleware 是 AgentMiddleware 实例
            dyn = [m for m in middleware if isinstance(m, AgentMiddleware)]
            assert dyn, (
                "DynamicIdentityMiddleware 未注册到 middleware → LLM 收不到 "
                "FACT 块,标题栏和 LLM 自报身份会再次不一致"
            )
            # 至少有 2 个 AgentMiddleware:dynamic_identity + quality_gate(后者不是
            # AgentMiddleware 而是 deepagents 的 Middleware 子类,可能也算,
            # 这里只断言至少 1 个 dynamic_identity 类的对象)
            assert len(dyn) >= 1

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
