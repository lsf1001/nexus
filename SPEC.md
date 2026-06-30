# Nexus 技术规格

## 架构

```
┌───────────────────────┐     HTTP / WebSocket      ┌──────────────────────────────────────────┐
│   React Frontend      │  ◄──────────────────────► │   FastAPI Backend (:30000)               │
│   Vite (:30077 dev)   │                           │                                          │
│   Tauri WebView (DMG) │                           │  入口(三选一):                              │
│                       │                           │   ├─ launcher.py     pywebview(legacy)   │
│  ├─ ChatArea          │                           │   ├─ runtime_main.py sidecar (Tauri DMG) │
│  ├─ Sidebar           │                           │   └─ main.py :app   FastAPI 共用入口     │
│  └─ ChannelInbox      │                           │                                          │
└───────────────────────┘                           │  ┌─ api/ws/* ─ WS 协议(6 子模块) ─────┐  │
                                                   │  │  auth / streaming / finalize /      │  │
                                                   │  │  observability / registry / handlers │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ channels/* ─ IM 通道 ──────────────┐  │
                                                   │  │  base / gateway / registry + 9 个     │  │
                                                   │  │  wechat_*.py / feishu / telegram    │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ agent/* ─ DeepAgents 封装 ─────────┐  │
                                                   │  │  _agent_builder / _system_prompt /   │  │
                                                   │  │  _subagents / _llm_factory /         │  │
                                                   │  │  _checkpoint / _backend              │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ middleware/* ── LLM 中间件链 ──────┐  │
                                                   │  │  dynamic_identity / force_tool /     │  │
                                                   │  │  hitl(path-aware 三态路由)            │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ quality/* + rubrics/* ─ 质量门 ────┐  │
                                                   │  │  QualityGateMiddleware /             │  │
                                                   │  │  MemoryFilter / RubricJudge /        │  │
                                                   │  │  Repair / Exporter / Meta-eval       │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ observability/* + intent/* ────────┐  │
                                                   │  │  EventSink / NexusLogHandler /       │  │
                                                   │  │  intent router (chitchat/knowledge)  │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ resilience/* ─ 韧性层 ─────────────┐  │
                                                   │  │  StreamGuard(重试) / Resume(续传)    │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ profiles/* + llm/* + mcp.py ──────┐  │
                                                   │  │  tier_routing / wrapper / policies   │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   │  ┌─ db.py + sessions.py + routes/* ───┐  │
                                                   │  │  SQLite(WAL+FK) / SessionManager    │  │
                                                   │  └─────────────────────────────────────┘  │
                                                   └──────────────────────────────────────────┘
                                                                   │
                                                                   ▼
                                                   ┌──────────────────────────────────────────┐
                                                   │  持久层 (~/.nexus/)                       │
                                                   │  ├─ nexus.db   SQLite(sessions/messages/  │
                                                   │  │              quality_scores/resume_   │
                                                   │  │              tokens/memory_legacy)    │
                                                   │  ├─ AGENTS.md  用户级长期记忆(可手编)      │
                                                   │  ├─ models.json 模型配置(原子写)         │
                                                   │  └─ logs/      EventSink JSONL 日志      │
                                                   └──────────────────────────────────────────┘
                                                                   │
                              deepagents MemoryMiddleware 自动注入  │
                                                                   ▼
                                                   ┌──────────────────────────────────────────┐
                                                   │  项目级记忆 nexus/.deepagents/AGENTS.md  │
                                                   │  (Nexus 身份/规则,**禁止手编**,Quality  │
                                                   │   GateMiddleware 拦截 LLM 写入做忠实度评估)│
                                                   └──────────────────────────────────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite + Tailwind CSS + Zustand |
| 后端 | FastAPI + DeepAgents + SQLite + Pydantic |
| 模型 | MiniMax / DeepSeek / Qwen (OpenAI SDK 兼容) |
| 桌面 APP | **Tauri 2**(Rust 主进程 + Python sidecar + 内嵌 WebView2/WKWebView,无 Electron / 无 Chromium) |

## 项目结构
```
nexus/                              # 仓库根
├── frontend/                       # React 19 SPA (独立目录)
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatArea.tsx        # WS 流式渲染 + HITL/Clarification 弹窗
│   │   │   ├── Sidebar.tsx         # 会话列表
│   │   │   ├── ChatBubble.tsx      # 单条消息
│   │   │   ├── ModelConfigModal.tsx
│   │   │   ├── WechatPluginModal.tsx
│   │   │   ├── ToastHost.tsx       # 全局 toast
│   │   │   ├── ErrorBoundary.tsx
│   │   │   └── desktop/            # 仅 Tauri DMG 用的壳组件
│   │   │       ├── DesktopShell.tsx
│   │   │       ├── ShellLayout.tsx
│   │   │       ├── SplashView.tsx  # 监听 runtime-status
│   │   │       ├── SettingsView.tsx
│   │   │       ├── SetupView.tsx
│   │   │       ├── ChatView.tsx
│   │   │       ├── ContextMenuHost.tsx
│   │   │       ├── WechatAssistantView.tsx
│   │   │       ├── SketchLines.tsx
│   │   │       ├── hooks/{useBootstrap,useConversationCrud,useDarkModeRoot}.ts
│   │   │       └── channels/{ChannelInbox,ChannelViewBase}.tsx
│   │   ├── hooks/                  # 通用 hooks
│   │   │   ├── useWebSocket.ts     # 浏览器 dev 模式
│   │   │   ├── useTauriWs.ts       # Tauri DMG 模式 (Rust relay)
│   │   │   ├── useWsConnection.ts  # WS 连接 + 重试
│   │   │   ├── useChannelStatusPolling.ts
│   │   │   └── useLoadingWatchdog.ts
│   │   ├── lib/{api,useContextMenuTrigger}.ts
│   │   ├── store/{useStore,useContextMenu,useToast}.ts   # Zustand
│   │   ├── types/index.ts          # StreamEvent union (18 种帧)
│   │   ├── App.tsx, main.tsx, vite-env.d.ts
│   ├── e2e/                        # Playwright 端到端
│   │   ├── helpers.ts
│   │   ├── chat-happy-path.spec.ts
│   │   ├── clarification.spec.ts
│   │   ├── hitl-confirm.spec.ts / hitl-confirm-mock.spec.ts
│   │   ├── multi-turn.spec.ts / reconnect.spec.ts
│   │   ├── reject-display.spec.ts / settings.spec.ts
│   │   ├── wechat-channel.spec.ts
│   │   ├── debug-agnes-message.spec.ts / diag-ws-page.spec.ts
│   ├── eslint.config.js, vite.config.ts, playwright.config.ts
│
├── desktop/                        # Tauri 2 桌面端 (当前生产 DMG)
│   ├── package.json                # cargo tauri dev/build
│   ├── frontend-dist/              # build 时由 frontend/dist 复制
│   └── src-tauri/
│       ├── src/
│       │   ├── main.rs             # Tauri 主进程入口
│       │   ├── runtime.rs          # sidecar supervisor (atexit kill, AppState, RuntimeStatus)
│       │   └── ws_relay.rs         # WS relay (ws_open / ws_send / ws_close)
│       └── build.rs
│
├── nexus/                          # Python 包 (src 布局)
│   ├── __init__.py
│   └── backend/
│       ├── main.py                 # FastAPI app + lifespan + 路由注册
│       ├── launcher.py             # macOS pywebview 入口 (legacy/dev)
│       ├── runtime_main.py         # Tauri sidecar 入口 (生产 DMG 用)
│       ├── run.py                  # dev 模式 `python nexus/backend/run.py`
│       ├── config.py               # 环境变量加载 + 优先级
│       ├── db.py                   # SQLite + PRAGMA + 自动 _ensure_column 迁移
│       ├── sessions.py             # SessionManager (idempotent / soft-delete)
│       ├── models.py               # Pydantic schema (WSMessage / Session / Message / HITL)
│       ├── models_config.py        # models.json 原子写 (tmp + fsync + os.replace)
│       ├── permissions.py          # 工具权限白名单
│       ├── mcp.py                  # MCP 插件加载
│       ├── tools.py                # 工具注册表
│       ├── api/
│       │   ├── ws/                 # WS 子包 (2026-06-30 拆分)
│       │   │   ├── __init__.py     # re-export 保证 monkeypatch 路径稳定
│       │   │   ├── auth.py         # token 校验 + 心跳
│       │   │   ├── streaming.py    # 流式 chunk + thinking_parser
│       │   │   ├── finalize.py     # final/done 帧 + add_message 持久化
│       │   │   ├── observability.py # intent 分类 + quality score 集成
│       │   │   ├── registry.py     # WS 客户端注册表
│       │   │   └── handlers.py     # 业务编排
│       │   └── thinking_parser.py  # <thinking> 标签状态机
│       ├── agent/                  # DeepAgents 封装
│       │   ├── _agent_builder.py   # create_agent() + middleware 链装配
│       │   ├── _system_prompt.py   # 静态 system prompt (身份/规则)
│       │   ├── _subagents.py       # code_writer / researcher
│       │   ├── _llm_factory.py     # get_llm() 实例
│       │   ├── _checkpoint.py      # AsyncSqliteSaver / MemorySaver 切换
│       │   └── _backend.py         # Filesystem / LocalShell / LangSmith / ContextHub
│       ├── middleware/             # deepagents AgentMiddleware 链
│       │   ├── dynamic_identity.py # [FACT] 块每次 LLM 调用前注入
│       │   ├── force_tool.py       # knowledge 类强制 yandex_search
│       │   └── hitl.py             # PathAwareHITLMiddleware (三态路由)
│       ├── quality/                # 质量门
│       │   ├── middleware.py       # QualityGateMiddleware (拦截 AGENTS.md 写)
│       │   └── memory_filter.py    # MemoryFilter (faithfulness 评分)
│       ├── rubrics/                # Phase 2 Rubric 系统
│       │   ├── judge.py            # RubricJudge (faithfulness / helpfulness 等)
│       │   ├── repair.py           # RepairService (低分自动修复)
│       │   ├── exporter.py         # DPO preference 导出
│       │   ├── meta_eval.py        # 元评测
│       │   ├── tool_evaluator.py
│       │   ├── prompts.py / schemas.py
│       ├── channels/               # IM 通道 (C5 重构)
│       │   ├── base.py / registry.py / gateway.py
│       │   ├── wechat_account.py / wechat_api.py / wechat_channel.py
│       │   ├── wechat_login.py / wechat_protocol.py / wechat_state.py
│       │   └── wechat_tokens.py / wechat_types.py
│       ├── observability/          # 产品事件 + LangChain callback
│       │   ├── events.py / sink.py (EventSink, JSONL 轮转)
│       │   ├── handler.py (NexusLogHandler, llm/tool/chain 回调)
│       │   └── logger.py
│       ├── intent/                 # 意图分类 (chitchat/knowledge/task/identity)
│       │   └── router.py
│       ├── llm/                    # LLM 包装层
│       │   ├── wrapper.py          # ResilientRunnable + StreamGuard
│       │   ├── policies.py         # 重试 / 降级策略
│       │   ├── errors.py           # 错误码 + 重试判定
│       │   └── e2e_mock.py         # 测试用 mock LLM
│       ├── profiles/               # 模型分层
│       │   └── tier_routing.py     # register_tier_profiles (弱/强模型 suffix)
│       ├── resilience/
│       │   ├── stream_guard.py     # 流式重试 + 事件计数
│       │   └── resume.py           # resume_token HMAC + 续传
│       ├── routes/
│       │   └── model_config.py     # REST /api/models CRUD
│       └── memory/__init__.py
│
├── scripts/                        # 维护脚本 (不入 wheel)
│   ├── build_dmg.sh                # cargo tauri build + hdiutil 打 DMG
│   ├── migrate_legacy_memory.py    # 一次性迁 v0.1 memory 表 → AGENTS.md
│   ├── seed_user_agents_md.py      # 幂等创建用户级 AGENTS.md
│   ├── eval_rubrics.py / verify_phase2.py
│   └── test_clarification_live.py
│
├── tests/                          # pytest 后端 (65 个测试文件)
│   ├── conftest.py / e2e_driver.py / real_llm_driver.py
│   ├── test_*.py                   # 按模块拆: agent_*, ws_*, db_*, rubric_*, ...
│
├── docs/
│   ├── architecture.md             # 产品模块图 + 逻辑架构图 (新增)
│   ├── data-flow/                  # 三张时序图 (新增)
│   │   ├── ws-main.md
│   │   ├── wechat-channel.md
│   │   └── memory-write.md
│   ├── operations/                 # 运维文档
│   ├── superpowers/                # 设计稿 / 计划 / 进度
│   ├── prototypes/ / refactor/
│   └── RELEASE_NOTES_v0.1.0.md
│
├── CLAUDE.md                       # AI 协作入口 (顶部 @python_project.md)
├── SPEC.md                         # 技术规格 (本文件)
├── README.md / CHANGELOG.md / AGENTS.md
├── python_project.md               # Python 工程硬性约束
├── pyproject.toml / package.json
└── verify-full.js                  # 顶层 e2e 入口
```

桌面 APP 当前是 **Tauri 2**:`scripts/build_dmg.sh` 走 `cargo tauri build` 产 .app,再 hdiutil 打 DMG。
- 主进程 `desktop/src-tauri/src/main.rs`(Rust)
- 后端通过 spawn **sidecar** `nexus-runtime`(`runtime_main.py`,轻量 FastAPI/uvicorn 二进制,**无 webview**)
- 前端 `frontend/dist` 由 Tauri 静态托管
- atexit 钩子在主进程退出时 SIGKILL sidecar,防止孤儿进程(`desktop/src-tauri/src/runtime.rs`)

legacy 入口 `launcher.py`(pywebview WKWebView)仍在仓库,仅作 dev 模式或回退使用,DMG 构建已不再走它。


## 核心模块

### 会话管理 (sessions.py)

- `SessionManager` - 线程安全单例
- `build_prompt()` - 构建带记忆的 prompt
- 支持软删除和恢复

### 记忆系统 (memory.py)

- `MemoryService` - BM25 检索
- `EvolutionService` - 记忆进化
- 记忆分类：preference / knowledge / context

### Agent (agent.py)

- `create_agent()` - 创建 DeepAgents Agent
- `create_subagents()` - 子代理（code_writer, researcher + 可选 AsyncSubAgent / CompiledSubAgent）
- `get_llm()` - LLM 实例创建
- `_create_store()` - langgraph Store（默认 AsyncSqliteStore 持久化,可切 InMemoryStore）
- `_create_checkpointer()` - langgraph checkpointer（默认 AsyncSqliteSaver,可切 MemorySaver）
- `_select_filesystem_backend()` - 选 backend（FilesystemBackend / LocalShellBackend / LangSmithSandbox / ContextHubBackend）
- `_ensure_registered()` - 注册 Nexus 的 ProviderProfile + HarnessProfile（minimax / minimax:MiniMax-M3）

#### DeepAgents 0.6.8 模块集成清单

| 模块 | 状态 | 入口 / 触发 |
| --- | --- | --- |
| `FilesystemBackend` | 默认 | `_select_filesystem_backend()` 默认分支 |
| `LocalShellBackend` | env-gated | `NEXUS_ENABLE_EXEC=1` |
| `LangSmithSandbox` | env-gated | `NEXUS_EXEC_BACKEND=langsmith` + `NEXUS_LANGSMITH_SANDBOX_NAME=<name>` |
| `ContextHubBackend` | env-gated | `NEXUS_EXEC_BACKEND=context_hub` + `NEXUS_CONTEXT_HUB_ID=<owner/name>` |
| `AsyncSqliteStore` | 默认 | `_create_store()` 默认分支 |
| `InMemoryStore` | 可选 | `NEXUS_STORE=memory` |
| `AsyncSqliteSaver` | 默认 | `_create_checkpointer()` 默认分支 |
| `MemorySaver` | 可选 | `NEXUS_CHECKPOINTER=memory` |
| `ProviderProfile` (minimax) | 默认 | `register_nexus_profiles()` |
| `HarnessProfile` + `GeneralPurposeSubagentProfile` | 默认 | `register_nexus_profiles()` |
| `AsyncSubAgent` (LangGraph Platform) | env-gated | `NEXUS_ASYNC_SUBAGENTS_JSON=[...]` |
| `CompiledSubAgent` (任意 Runnable) | env-gated | `NEXUS_COMPILED_SUBAGENTS_JSON=[...]` |
| `SkillsMiddleware` + `SKILL.md` | 默认 | `.nexus/skills/<name>/SKILL.md` |
| `MemoryMiddleware` + AGENTS.md | 默认 | `make_memory_paths()`(用户级 + 项目级) |
| `PathAwareHITLMiddleware`(HITL 三态路由) | 默认 | `nexus/backend/agent/_agent_builder.py::create_agent` middleware 链 |
| `ForceToolMiddleware`(弱模型不调工具反模式) | 默认 | `nexus/backend/middleware/force_tool.py` |
| `DynamicIdentityMiddleware`(FACT 块实时注入) | 默认 | `nexus/backend/middleware/dynamic_identity.py` |
| `QualityGateMiddleware`(AGENTS.md 写忠实度拦截) | 默认 | `nexus/backend/quality/middleware.py` |

⚠️ **execution backend 警告**:LocalShellBackend / LangSmithSandbox / ContextHubBackend 让
LLM 可以执行 shell / 远程代码。deepagents 0.6.8 的 FilesystemMiddleware 不支持同时配
permissions 和 execution backend(框架会主动禁用 permissions)。生产建议禁用,
本地开发 / CI 测试按需开启。

### 中间件链(middleware,顺序敏感,2026-06-29 重构 + 2026-06-30 追加)

`create_deep_agent(middleware=[...])` 的中间件顺序由外到内,langchain 第一个是最外层最后执行:

```
[quality_gate → path_aware_hitl → dynamic_identity → force_tool]
```

- **`quality_gate`** — 拦截 AGENTS.md 写入的忠实度评估(配合 `MemoryMiddleware`),对应 `nexus/backend/quality/middleware.py::QualityGateMiddleware`
- **`path_aware_hitl`** — 路径感知 HITL:**protected**(AGENTS.md 类)透传给 quality_gate;**HITL**(项目源码 / `/tmp` / 全局 `.git/` 等)触发 GraphInterrupt → WS `confirmation_request` 帧;**deny 白名单** (`.nexus/skills/*` 等)直接透传。详见 `nexus/backend/middleware/hitl.py`
- **`dynamic_identity`** — 每次 LLM 调用前实时读 `~/.nexus/models.json`,把 `[FACT · 当前驱动模型]` 块 prepend 到 `request.system_message.content` 最前面,解决标题栏与 LLM 回答的模型串味
- **`force_tool`** — knowledge 类问题("BTC 还能涨吗" / "元力股份 能买吗")LLM 第一次响应没调工具时,自动 patch 一个 `yandex_search` tool_call 强制走事实检索;**task 类不再强制**(2026-06-30 收紧,反模式修复)

WHY 走 middleware 不走 permissions:deepagents 0.5.3 不支持 permissions 写入 `mode="interrupt"`(被静默忽略);middleware 是 framework-stable 钩子,跨版本兼容。NEXUS_CONTEXT_WINDOW 等模型默认参数也通过 `HarnessProfile` + `register_tier_profiles()` 注入(弱模型 `_WEAK_SUFFIX` + 强模型 `_FULL_SUFFIX`),不走 middleware 层。

### WebSocket (main.py)

- `/api/ws?token=<NEXUS_WS_TOKEN>` - 实时对话端点(鉴权用 `hmac.compare_digest` 防时序攻击)
- 流式响应(完整 18 种帧,定义在 `frontend/src/types/index.ts::StreamEvent`):

  **主路径帧(server → client)**: `thinking` → `chunk` → `tool_call` / `tool_result` → `final` → `done`

  **辅帧(server → client)**:
  - `error` — 错误(LLM / WS 启动失败 / 通用)
  - `token_usage` — token 计数 + 上下文使用率
  - `channel_message` — IM 通道消息广播(替代 v0.1 的 `wechat_message`)
  - `session_created` — 新会话创建
  - `resume_token` / `resume_ack` / `invalid_resume_token` — 断点续传握手
  - `stats` — 可观测元事件(retries / fallbacks / events_emitted)
  - `clarification_request` — ask_user 工具触发的前端澄清弹窗
  - `confirmation_request` — HITL 待审批动作(对应 langchain `GraphInterrupt`)

  **反向帧(client → server)**:
  - `WSMessage(content, session_id?, title?)` — 主对话消息
  - `ConfirmationResponseFrame(decision)` — HITL 决策回传

- 支持多客户端 + 断线重连(resume_token 表 + `last_event_id` 续传)
- **`ws/` 包结构**(2026-06-30 拆分,回落到 §1.2 单文件 ≤ 800 行):
  - `__init__.py` — re-export `add_message` / `handle_websocket` 等公开符号,保证 `mock.patch("nexus.backend.api.ws.add_message")` 路径稳定
  - `auth.py` — WS 鉴权(token 校验 + 心跳)
  - `streaming.py` — 流式 chunk + thinking parser
  - `finalize.py` — final / done 帧 + add_message 持久化
  - `observability.py` — intent 分类 / quality score 集成
- 生产代码用 `from ... import db as _db` 而非 `from ...db import add_message`(monkeypatch-friendly;见 `feedback-monkeypatch-module-state.md`)

### 微信通道 (channels/wechat.py)

- 二维码登录
- 消息回调处理
- 自动会话创建

## 数据库

`nexus.db`(单文件 SQLite,位置 `~/.nexus/nexus.db`)。`db.py::get_db()` 在连接建立时执行 PRAGMA:
```sql
PRAGMA foreign_keys=ON       -- 默认关闭,显式开启级联
PRAGMA journal_mode=WAL      -- 并发读优化
PRAGMA synchronous=NORMAL    -- WAL 模式下 fsync 折中
PRAGMA busy_timeout=30000    -- 抗 aiosqlite 写锁等待(30s 是 SQLite 默认上限)
```

### 表结构(共 5 张)

```sql
-- 会话 (主索引 channel, 支持主会话 / 微信 / 飞书 / Telegram 多通道)
sessions(
  id TEXT PRIMARY KEY,
  title TEXT,
  channel TEXT DEFAULT 'main',        -- main / wechat / feishu / telegram
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT                       -- 软删除,purge_old_sessions 30 天后清
)
CREATE INDEX idx_sessions_updated_at ON sessions(updated_at DESC);
CREATE INDEX idx_sessions_deleted_at  ON sessions(deleted_at);

-- 消息 (FK → sessions ON DELETE CASCADE)
messages(
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  thinking_content TEXT,                -- 可空,assistant 的 <thinking> 块
  intent TEXT,                          -- chitchat / knowledge / task / NULL
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
CREATE INDEX idx_messages_session_id ON messages(session_id);

-- 质量评分 (Phase 2 rubric LLM 评分,accept/repair/reject 决策依据)
quality_scores(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  message_id TEXT,                      -- 可空(评分可不对应具体消息)
  rubric TEXT NOT NULL,                 -- faithfulness / helpfulness / ...
  score REAL NOT NULL,                  -- 0.0-1.0
  verdict TEXT NOT NULL,                -- accept / repair / reject
  reasoning TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
CREATE INDEX idx_quality_session ON quality_scores(session_id);

-- 断点续传 token (resilience/resume.py HMAC, 续传时校验)
resume_tokens(
  token TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  last_event_id INTEGER NOT NULL,       -- 该 session 流到的最后 event_id
  expires_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
CREATE INDEX idx_resume_tokens_session ON resume_tokens(session_id);

-- v0.1 旧记忆表 (只读, v0.2+ 数据已迁到 AGENTS.md, 保留供 grep 历史)
memory_legacy(
  id TEXT PRIMARY KEY,
  memory_type TEXT CHECK (memory_type IN ('explicit', 'evolved', 'session')),
  category TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  metadata TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT,
  is_active INTEGER DEFAULT 1
)
CREATE INDEX idx_memory_type     ON memory_legacy(memory_type);
CREATE INDEX idx_memory_category ON memory_legacy(category);
CREATE INDEX idx_memory_key      ON memory_legacy(key);
CREATE INDEX idx_memory_updated  ON memory_legacy(updated_at DESC);
CREATE INDEX idx_memory_active   ON memory_legacy(is_active);
```

### 迁移策略

- **新增列**:`db.py::get_db()` 通过 `_ensure_column()` 兼容老库(缺列则 `ALTER TABLE ADD COLUMN`),**无需手工迁移脚本**。
- **v0.1 → v0.2 记忆迁移**(一次性):`scripts/migrate_legacy_memory.py` 把旧 `memory` 表 `is_active=1 AND memory_type='explicit'` 的行迁到 `~/.nexus/AGENTS.md`,然后 `ALTER TABLE memory RENAME TO memory_legacy` + `VACUUM`。**幂等**:已迁过的(`memory_legacy` 已存在)直接退出 0。

### 当前未使用 / 已废弃

| 表 | 状态 | 说明 |
|----|------|------|
| `memory` | ❌ 废弃 | 已 RENAME TO `memory_legacy`(v0.2 重构) |
| `memory_legacy` | 🟡 只读 | 数据保留供 grep 历史,新代码不写 |
| `tool_stats` / `session_stats` | ❌ 不存在 | SPEC v0.1 提及但代码从未实现,已删除 |


## CLI

2026-06 清理：产品不再提供 CLI（`nexus/cli/` 整包删除）。终端用户走 macOS DMG APP（`/Applications/Nexus.app`，Tauri 主进程 spawn sidecar `nexus-runtime` 拉起后端），开发者从 git clone 走源码直跑：

```bash
# 后端（一个 terminal，30000 端口）
source .venv/bin/activate
python nexus/backend/run.py

# 前端（另一个 terminal，30077 端口）
(cd frontend && npm run dev)
```

历史 `nexus install/start/stop/status/logs/doctor/setup/config` 全部失效。


## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMAX_API_KEY` | - | API Key (优先) |
| `MINIMAX_API_BASE` | https://api.minimaxi.com/v1 | 端点 |
| `NEXUS_WS_TOKEN` | nexus-default-token | WebSocket 认证 |
| `NEXUS_PORT` | 30000 | 端口 |
| `NEXUS_ENABLE_MCP` | true | 启用 MCP |
| `NEXUS_ALLOWED_ORIGINS` | `*` (dev) | CORS 允许来源,逗号分隔 |

API Key 兼容：`MINIMAX_API_KEY` > `MiniMax_API_KEY` > `ANTHROPIC_AUTH_TOKEN` > `ANTHROPIC_API_KEY`，首次匹配胜出。`ANTHROPIC_BASE_URL` 同理兼容。

## 实现说明

最近一轮稳定性修复（已通过 83 项 E2E 验证 + 558 项 pytest 单测）：

- **PRAGMA 启用**：`db.py` 在连接建立时执行 `foreign_keys=ON`、`journal_mode=WAL`、`synchronous=NORMAL`，避免跨表引用失败和断电丢数据
- **模型配置原子写**：`models_config.save_models()` 走 `tmp + fsync + os.replace` 流程，写失败不污染原文件
- **REST 状态码语义**：`routes/model_config.py` 使用 `HTTPException` + 标准状态码（404/409/400/201/422），不再返回 `{"success": false}`
- **CORS 白名单**：`NEXUS_ALLOWED_ORIGINS` 控制允许来源；dev 默认通配，生产可收紧
- **BM25 增量缓存**：`MemoryService` 按 `(id, key, value)` 签名复用分词结果，未变化文档不重算
- **用户消息去重**：连续相同 `content` 在 2s 内只触发一次 LLM 调用，避免误触重发
- **WS 跨线程桥接**：流式回调在子线程中通过 `asyncio.run_coroutine_threadsafe` 投递回事件循环，不阻塞通道
- **HITL 三态路由**(2026-06-30)：`nexus/backend/middleware/hitl.py::PathAwareHITLMiddleware` 在 `wrap_tool_call` 阶段对"非白名单 + 非 protected 写工具"主动抛 `GraphInterrupt`,WS handler 转 `confirmation_request` 帧回放给前端。三态: `protected` (AGENTS.md) → quality_gate 透传 / `HITL` (项目源码) → 弹窗 / `deny 白名单` (`.nexus/skills/*`) → 透传。修复 deepagents `mode="interrupt"` 在 0.5.3 被静默忽略的 5 个 E2E 场景全 FAIL。
- **ws 包层 re-export**(2026-06-30)：`api/ws/__init__.py` 重新导出 `add_message`,`api/ws/{finalize.py, streaming.py, observability.py}` 改 `from ... import db as _db` 模式。修复 6 个测试 AttributeError + monkeypatch 看不到生产侧对象的隐性 bug。
- **ForceToolMiddleware `force_intents` 收紧**(2026-06-30)：从 `("knowledge", "task")` 改为 `("knowledge",)`。task 类问题(写代码 / 写文件)由 LLM 自决,knowledge 类(BTC / 元力股份)继续强制 patch `yandex_search`。修复把 task 推上搜索循环的死锁。
- **前端 TS strict 修复**(2026-06-30)：`ToastHost.tsx` 补 `KindColor` interface + fallback / `useWsConnection.ts` 合并 `isTauri` 字段。修复 `cd frontend && tsc -b --noEmit` 2 类 4 处报错阻塞 DMG 构建。

---

*最后更新: 2026-06-30*
