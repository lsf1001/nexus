"""主 Agent 工厂:``create_agent`` 把所有组件装配成 deepagents 实例。

模块化拆分后,本模块集中承载:

- :func:`create_agent` — 唯一对外的 agent 工厂入口;组装 LLM / backend /
  checkpointer / store / subagents / permissions / memory / middleware
- 各种 ``_os`` / ``Path`` / logger 局部 import 以满足 PyInstaller frozen 模式
  启动性能(详见模块顶部的注释)

WHY 单独成包:``create_agent`` 是 deepagents 集成的"主控流程",把所有
副作用(初始化 checkpointer、注册 tier profile、挂 middleware)按**顺序
敏感**组装在一起,集中一个文件便于审阅顺序约束 + 未来插入新 middleware。
"""

from __future__ import annotations

import os as _os
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)


def create_agent(
    model_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    temperature: float | None = None,
    mcp_tools: list[Any] | None = None,
) -> Any:
    """创建带完整 Nexus 能力的智能体。

    集成 DeepAgents SDK 全部模块:
    - CompositeBackend: 多 backend 组合
    - FilesystemMiddleware: 文件权限控制(通过 permissions 参数)
    - MemoryMiddleware: 记忆系统(通过 memory 参数)
    - SummarizationMiddleware: 对话摘要(自动添加)
    - SubAgentMiddleware: 子代理协作(通过 subagents 参数)

    Args:
        model_name: 模型名称
        api_key: API 密钥
        api_base: API 端点
        temperature: 温度参数
        mcp_tools: MCP 服务器加载的工具列表
    """
    from deepagents import create_deep_agent

    from ..config import CONFIG
    from ..tools import TOOLS
    from ._backend import _create_backend
    from ._checkpoint import _create_checkpointer, _create_store
    from ._llm_factory import get_llm
    from ._subagents import create_subagents
    from ._system_prompt import get_project_root, get_system_prompt

    project_root = get_project_root()
    skills_dir = project_root / ".nexus" / "skills"

    # 注册 Nexus 的 LLM provider / harness profiles(MiniMax-M3 + minimax family)。
    # WHY 在 create_agent 入口调:deepagents 的 profile registry 是全局的,
    # 必须在 create_deep_agent() 之前注册,否则它 resolve_model 时拿不到
    # 我们的 init_kwargs / system_prompt_suffix。
    from ..profiles import _ensure_registered

    _ensure_registered()

    # 合并 MCP 工具和内置工具
    all_tools = list(TOOLS)
    if mcp_tools:
        all_tools.extend(mcp_tools)

    # 创建 LLM 实例
    if _os.environ.get("NEXUS_E2E_MOCK") == "1":
        # E2E mock 路径:仅 ``NEXUS_E2E_MOCK=1`` 启用,场景由 NEXUS_E2E_SCENARIO 决定。
        # 平时完全不加载 — 不影响生产。详见 nexus.backend.llm.e2e_mock。
        from ..llm.e2e_mock import make_e2e_mock_llm

        llm = make_e2e_mock_llm()
        logger.warning("[E2E-MOCK] using mock LLM scenario=%s", llm.scenario)
    else:
        llm = get_llm(model_name, api_key, api_base, temperature)

    # 顺序敏感:**先 checkpointer 再 store**。
    # _create_checkpointer() 走 sync sqlite3 + 同步 DDL(``_ensure_sqlite_checkpoint_tables``),
    # 调完就关连接、不留后台线程。_create_store() 走 aiosqlite,内部 ``asyncio.run``
    # 起一个 loop、``AsyncSqliteStore.setup()`` 在 loop 内 DDL 后 aiosqlite 连接
    # 保持打开(WAL 模式持写锁直到连接关)。如果先 store 再 checkpointer,aiosqlite
    # 的 WAL 写锁会让后续 sync sqlite3 的 DDL 直接 OperationalError: database is
    # locked(同库双连接,busy_timeout 也救不了,aiosqlite 持锁期间 sync 必失败)。
    # 倒过来:sync DDL 一次性完成,aiosqlite 后开连接不复用锁。
    checkpointer = _create_checkpointer()

    # 持久化 store:挂 /memories/ 路由供 LLM 跨 session 读写。
    # SqliteStore 把数据落 ~/.nexus/nexus.db,跟 checkpoint 同一库 —
    # 跨进程 / 跨重启存活(InMemoryStore 只在进程内,重启丢光)。
    # WHY 选 SqliteStore(不是 InMemoryStore):AGENTS.md 之外的 LLM 临时记忆
    # (用户偏好 / 项目约定 / 中间结果)跨进程共享,跟 checkpoint 同寿命。
    store = _create_store()

    # 创建 backend(挂 StoreBackend 到 /memories/ 路由)
    backend = _create_backend(project_root, store=store)

    # 子代理(复用主模型的 LLM 实例)
    subagents = create_subagents(model=llm)

    # 权限规则(白名单 .nexus/,AGENTS.md 与项目源码的 HITL/QualityGate
    # 由专门中间件接管,见下方 path_aware_hitl / quality_gate)。
    from ..permissions import build_default_permissions, resolve_protected_paths

    permissions = build_default_permissions(project_root)

    # 记忆路径 —— 用户级长期记忆文件。Nexus 是个人智能助理(对标 OpenClaw),
    # 没有"项目级 AGENTS.md"概念;deepagents MemoryMiddleware 会自动加载
    # 单条路径并以 ``<agent_memory>...</agent_memory>`` 注入 system prompt。
    # 文件不存在时 MemoryMiddleware 静默跳过(降级为空段),
    # 不影响 LLM 启动 —— 产品身份由 ``_build_system_prompt`` 硬编码兜底。
    from ..memory import USER_MEMORY_PATH

    memory_files: list[str] = [str(USER_MEMORY_PATH)]

    # 质量门:拦截对受保护 AGENTS.md 的 edit_file / write_file 写入
    # 事实校验中间件（2026-07 plan）:拦截 LLM 输出,扫描日期/星期/数学/单位/
    # 汇率类确定性事实冲突。与 quality_gate 互补:quality_gate 守
    # ``wrap_tool_call``(写 AGENTS.md 前评估),fact_check 守 ``wrap_model_call``
    # (LLM 输出后扫描)。fail_strategy="closed":任何冲突抛 FactCheckError,
    # 让 LLM 看到 ToolMessage error 触发自纠。
    from ..agents.middleware import FactCheckMiddleware
    from ..quality.memory_filter import MemoryFilter
    from ..quality.middleware import QualityGateMiddleware
    from ..rubrics.judge import RubricJudge
    from ..rubrics.schemas import FAITHFULNESS_RUBRIC

    fact_check = FactCheckMiddleware(fail_strategy="closed")

    quality_gate = QualityGateMiddleware(
        filter=MemoryFilter(judge=RubricJudge(llm=llm), rubric=FAITHFULNESS_RUBRIC),
        protected_paths=tuple(str(p) for p in resolve_protected_paths(project_root)),
    )

    # 路径感知 HITL(2026-06-29 修复):对"非白名单"的写工具触发 GraphInterrupt,
    # 让 WS 端发 confirmation_request 帧。原先写进 permissions 的
    # ``mode="interrupt"`` 是 deepagents 0.5.3 不支持的非法值,被静默忽略,
    # 导致 E2E 5 个场景(写项目源码 / /tmp / 多 tool_call / reject-then-reflect
    # / edit_file)全部 FAIL — LLM 写源码无 HITL 弹窗,直接落盘。
    # 见 :mod:`nexus.backend.middleware.hitl` 实现细节。
    from ..middleware.hitl import PathAwareHITLMiddleware

    path_aware_hitl = PathAwareHITLMiddleware(
        project_root=project_root,
        protected_paths=tuple(str(p) for p in resolve_protected_paths(project_root)),
    )

    # 动态身份 middleware:每次 LLM 调用前**实时**从 ``~/.nexus/models.json``
    # 读当前 active model,把 ``[FACT · 当前驱动模型]`` 块 prepend 到
    # ``request.system_message.content`` 的最前面。这是修复 E2E 2026-06-29
    # "标题栏显示 MiniMax-M3,LLM 答 agnes-2.0-flash" 串味 bug 的核心机制:
    # 把"FACT 块"从"在 create_agent 时拼字符串"挪到"在每次 LLM 调用前注入",
    # 单一数据源(models.json),绝无缓存滞留。
    from ..middleware.dynamic_identity import dynamic_identity_middleware

    # 上下文自动压缩:由 deepagents 0.6.8 主 agent stack 自动注入
    # ``create_summarization_middleware(model, backend)``,trigger 通过
    # ``ResilientRunnable._resolve_model_profile()`` 暴露的 profile 计算:
    #   1. profile 含 max_input_tokens → deepagents 用 ``("fraction", 0.85)``,
    #      实际触发阈值 = max_input_tokens × 0.85
    #   2. profile 缺 max_input_tokens → fallback 到 ``("tokens", 170000)``,
    #      对 200K 模型几乎不触发,要避免
    # Nexus 当前 profile.max_input_tokens = NEXUS_CONTEXT_WINDOW(默认 200K),
    # 实际触发阈值 = 200000 × 0.85 = 170000 tokens。
    # **不要**自己再传一个 SummarizationMiddleware —— 两个同名 middleware
    # 会让 langchain factory 抛 ``AssertionError: Please remove duplicate
    # middleware instances``,E2E 2026-06-27 ``test_e2e_04_models_crud`` 暴露
    # (触发场景:``POST /api/models/switch`` 重建 agent 时炸 500)。
    # 旧 commit ``c6d6f56`` 基于"deepagents 默认 trigger=None"错误前提,
    # 实际是 ``compute_summarization_defaults`` 会按 model profile 给出
    # 非空 trigger,完全够用。
    # ``checkpointer`` 已在上面 _create_store() 之前构造(顺序敏感,见那段注释)。
    # 2026-06-29 重构:在 create_deep_agent 之前注册 HarnessProfile tier 路由。
    # 必须先于 create_deep_agent 调用,否则 resolve_model 时拿不到 spec 匹配。
    from ..profiles.tier_routing import register_tier_profiles

    register_tier_profiles()

    # 2026-06-29 重构:加 ForceToolMiddleware —— 弱模型(MiniMax-M3)问投资
    # 类问题不调 yandex_search,LLM 答非所问。本中间件在 LLM 第一次响应没
    # 调工具时,自动 patch 一个 yandex_search tool_call,强制走事实检索。
    # 2026-06-30 修正:``force_intents`` 只含 ``knowledge``,不再含 ``task``。
    # 历史版本("knowledge","task")把"帮我把 print 写到 foo.py"这种 task
    # 也强制 patch yandex_search → LLM 拿到搜索结果不知何用,又触发新一
    # 轮无 tool_call → 死循环。task 类工具选择很广(write_file/edit_file
    # / str_replace_editor 等),由 LLM 自决,避免错误引导。
    from ..middleware.force_tool import ForceToolMiddleware

    force_tool_mw = ForceToolMiddleware(force_intents=("knowledge",))

    agent = create_deep_agent(
        model=llm,
        tools=all_tools,
        # 2026-06-29 重构:``_build_system_prompt`` 只输出与激活模型无关的
        # 产品规则(身份 / 思考格式 / 澄清 / 安全)。模型特定指令由
        # HarnessProfile 的 ``system_prompt_suffix`` 按 provider:model 注入。
        system_prompt=get_system_prompt(model_name or CONFIG.get("model_name", "")),
        backend=backend,
        subagents=subagents,
        permissions=permissions,
        memory=memory_files,
        store=store,
        # middleware 顺序(由外到内,langchain 第一个是最外层最后执行):
        #   quality_gate      : 拦截 AGENTS.md 写入忠实度评估(配合 MemoryMiddleware)
        #   path_aware_hitl   : 对"非白名单"写工具触发 GraphInterrupt → confirmation_request
        #   dynamic_identity  : prepend FACT 块(注入当前激活模型)
        #   fact_check        : 拦截 LLM 输出,扫描日期/数学/汇率冲突(fail-closed)
        #   force_tool        : knowledge/task 类问题强制 LLM 调 yandex_search
        # path_aware_hitl 与 quality_gate 顺序: quality_gate 先(它只关心
        # AGENTS.md,直接透传其它路径);path_aware_hitl 后,对透传过来的
        # "非白名单 + 非 protected" 路径触发 HITL。
        # fact_check 位置: 在 dynamic_identity 后(已注入 FACT 块)、force_tool 前
        # — 让 force_tool 仍可对"无 tool_call 的弱模型"打补丁,但 fact_check
        # 已经看到的输出是含 FACT 块的最终文本。
        middleware=[
            quality_gate,
            path_aware_hitl,
            dynamic_identity_middleware,
            fact_check,
            force_tool_mw,
        ],
        checkpointer=checkpointer,
        skills=[
            ".nexus/skills",
        ]
        if skills_dir.exists()
        else [],
    )

    # 总是挂 NexusLogHandler(走 setup_logging 的 EventSink,JSONL/text 落盘)
    from ..observability import EventSink, NexusLogHandler

    # EventSink 是全局单例,由 setup_logging() 在 main.py 启动期创建并 attach 到
    # ``logging.getLogger("nexus.observability")`` 的 handler 上。但 callback 需要
    # 显式 sink 实例,所以从环境变量解析路径重建一个。
    _sink_path = Path(
        _os.environ.get("NEXUS_LOG_FILE", str(Path.home() / ".nexus" / "logs" / "nexus.log"))
    ).expanduser()
    _sink_fmt = _os.environ.get("NEXUS_LOG_FORMAT", "text")
    agent._nexus_log_handler = NexusLogHandler(sink=EventSink(path=_sink_path, format=_sink_fmt))

    # 排障模式额外挂 StdOutCallbackHandler(text 调试用,生产不开启)
    if _os.environ.get("NEXUS_AGENT_VERBOSE") == "1":
        from langchain_core.callbacks import StdOutCallbackHandler

        # 深 agents / LangGraph 把 callbacks 存在 .config;挂到 agent config 入口
        # 副作用:每次 astream 时 ws.py 的 RunnableConfig 也得带这个 handler。
        # 这里只挂在 agent 上,下次 astream 时由 ws.py 注入。
        agent._nexus_verbose_handler = StdOutCallbackHandler()
        logger.info("NEXUS_AGENT_VERBOSE=1, 已挂 StdOutCallbackHandler 到 agent(排障模式)")
    else:
        agent._nexus_verbose_handler = None

    return agent
