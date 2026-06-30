# 文档对齐代码 实施计划

> **For agentic workers:** 文档工作,无单测。每个 task 完成后用 `git diff` 自检。

**Goal:** SPEC.md / CLAUDE.md / docs/architecture.md / docs/data-flow/ 跟当前代码对齐到一致。

**依据:** 上一轮对代码的 codegraph_explore + Read SPEC.md + grep 文档目录;调研时间 2026-07-01。

---

## Task 1 (P0-2): SPEC.md 架构图重画

**File:** `SPEC.md` lines 5-18

**改前 (v0.1 旧图):**
```
┌─────────────┐         HTTP/WebSocket        ┌─────────────┐
│   React     │ ◄─────────────────────────────► │   FastAPI   │
│   Frontend  │                              │   Backend   │
│   (:30077)  │                              │   (:30000)  │
└─────────────┘                              └──────┬──────┘
                                                    │
                           ┌────────────────────────┼────────────────────────┐
                           │                        │                        │
                    ┌──────▼──────┐          ┌──────▼──────┐          ┌──────▼──────┐
                    │  Session    │          │   Memory    │          │    MCP      │
                    │  Manager    │          │   Service   │          │   Plugin    │
                    └────────────┘          └────────────┘          └────────────┘
```

**改后:**
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

**关键修正:**
- 删 `Memory Service` 框(v0.2+ 完全迁出,改由 deepagents MemoryMiddleware 注入 2 份 AGENTS.md)
- 加 7 个真实子系统盒(不是 3 个)
- 加 3 个 Python 入口区分(launcher / runtime_main / main)
- 加 Tauri WebView 作为 DMG 端(替代 React 直连)
- 加持久层 + 项目级记忆块

---

## Task 2 (P0-3): SPEC.md 项目结构重画

**File:** `SPEC.md` lines 31-55

**改前:**
```
nexus/                 # 仓库根
├── frontend/          # React SPA (独立目录)
│   ├── src/
│   │   ├── components/   # ChatArea, Sidebar, ChatBubble...
│   │   ├── hooks/        # 自定义 Hook
│   │   ├── store/        # Zustand 状态
│   │   ├── types/        # TypeScript 类型
│   │   └── App.tsx
│   ├── tests/e2e/     # Node 端到端 (Playwright + WS)
│   └── vite.config.ts
├── nexus/             # Python 包
│   ├── backend/        # FastAPI 后端
│   │   ├── main.py     # 入口 + lifespan + WebSocket
│   │   ├── config.py   # 配置加载 (env 优先级)
│   │   ├── agent.py    # DeepAgents 封装
│   │   ├── sessions.py # SessionManager
│   │   ├── memory.py   # MemoryService + BM25 + 进化
│   │   ├── db.py       # SQLite + 迁移
│   │   ├── models_config.py # models.json 原子写
│   │   ├── routes/     # REST 路由 (model_config 等)
│   │   ├── channels/   # wechat, base, registry
│   │   └── plugins/    # MCP / 工具插件
└── tests/             # pytest (后端)
```

**改后:**
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
│   │   │   ├── useTauriWs.ts       # Tauri DMG 模式(Rust relay)
│   │   │   ├── useWsConnection.ts  # WS 连接 + 重试
│   │   │   ├── useChannelStatusPolling.ts
│   │   │   └── useLoadingWatchdog.ts
│   │   ├── lib/{api,useContextMenuTrigger}.ts
│   │   ├── store/{useStore,useContextMenu,useToast}.ts   # Zustand
│   │   ├── types/index.ts          # StreamEvent union(18 种帧)
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
├── SPEC.md                         # 技术规格 (本文件正在更新)
├── README.md / CHANGELOG.md / AGENTS.md
├── python_project.md               # Python 工程硬性约束
├── pyproject.toml / package.json
└── verify-full.js                  # 顶层 e2e 入口
```

**关键修正:**
- 删 `agent.py` → 改 `agent/_*.py` 7 个子文件
- 删 `memory.py` (已迁 AGENTS.md)
- 删 `plugins/` → 改 `mcp.py` 直接在 `backend/` 根
- `channels/wechat.py` → 11 个 wechat_*.py 拆分
- 加 `desktop/src-tauri/` (Tauri 生产路径)
- 加 `frontend/src/components/desktop/` (Tauri 专用壳)
- 加 `frontend/src/hooks/useTauriWs.ts` (DMG 模式)
- 加 `middleware/`, `quality/`, `rubrics/`, `intent/`, `llm/`, `profiles/`, `resilience/`, `observability/`, `channels/(11)`, `routes/`
- 加 `docs/architecture.md` + `docs/data-flow/`

---

## Task 3 (P0-4): SPEC.md 数据库重写

**File:** `SPEC.md` lines 145-167

**改前:**
```sql
-- 会话
sessions(id, title, channel, deleted_at, created_at, updated_at)

-- 消息
messages(id, session_id, role, content, thinking_content, created_at)

-- 记忆（单数表名）
memory(
  id, session_id, category, memory_type, key, value,
  source, confidence, is_active, created_at, updated_at
)

-- 工具调用统计
tool_stats(tool_name, call_count, success_count, last_called_at)

-- 会话级统计
session_stats(session_id, message_count, total_tokens, last_active_at)
```

**改后:**
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
CREATE INDEX idx_sessions_deleted_at ON sessions(deleted_at);

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

-- v0.1 旧记忆表(只读,v0.2+ 数据已迁到 AGENTS.md,保留供 grep 历史)
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
```

**关键修正:**
- 删 `memory` 表 (已 RENAME TO memory_legacy)
- 删 `tool_stats` / `session_stats` (代码里不存在)
- 加 `quality_scores` (Phase 2)
- 加 `resume_tokens` (断点续传)
- `memory_legacy` 加注释说明只读
- 加 FK / CHECK / INDEX 信息

---

## Task 4 (P1-1): SPEC.md WS 帧序列扩完整

**File:** `SPEC.md` line 129

**改前:**
```text
流式响应：`thinking` → `chunk` → `confirmation_request`(HITL 路径)→ `final` → `done`
```

**改后:**
```text
WS 帧序列(完整 18 种,见 frontend/src/types/index.ts StreamEvent union):

服务端 → 客户端:
  thinking / chunk / tool_call / tool_result / final / done
  error / token_usage / channel_message
  session_created / resume_token / resume_ack / invalid_resume_token
  stats / clarification_request / confirmation_request

客户端 → 服务端:
  WSMessage(content, session_id?, title?)            # 主对话
  ConfirmationResponseFrame(decision)                # HITL 决策
```

---

## Task 5 (P0-1 + P2-2): CLAUDE.md 修改

**File:** `CLAUDE.md`

**5a. Line 4 技术栈修正**

改前:
```
- 技术栈：React 19 + FastAPI + DeepAgents + WebSocket + SQLite + Electron
```

改后:
```
- 技术栈：React 19 + FastAPI + DeepAgents + WebSocket + SQLite + Tauri 2（macOS DMG）
- 桌面端：DMP 生产 = Tauri 2（scripts/build_dmg.sh 走 cargo tauri build）
        pywebview (launcher.py) 仅 legacy/dev fallback
```

**5b. Line 70 DMG 描述对齐**

改前:
```
- `scripts/build_dmg.sh`：PyInstaller onedir + .app bundle 构造 + hdiutil 打 DMG
```

改后:
```
- `scripts/build_dmg.sh`：Tauri 2 (`cargo tauri build`) + hdiutil 打 DMG
  (历史 PyInstaller + pywebview 已废弃, 见 `desktop/src-tauri/`)
```

**5c. Line 63 §关键约束 第 1 条 (P2-2)**

改前:
```
- **WebSocket 协议** `/api/ws`，流式响应：`thinking` → `chunk` → `final` → `done`，支持多客户端
```

改后:
```
- **WebSocket 协议** `/api/ws?token=...`，流式响应（完整 18 种帧，见 SPEC.md §WebSocket）：
  `thinking` → `chunk` → `tool_call` / `tool_result` → `final` → `done`
  辅帧：`error` / `token_usage` / `channel_message` / `session_created` /
  `resume_token` / `resume_ack` / `invalid_resume_token` / `stats` /
  `clarification_request` / `confirmation_request`
  支持多客户端 + 断点续传（resume_token 表 + last_event_id）
```

---

## Task 6 (P1-2): 新建 docs/architecture.md

**File:** `docs/architecture.md` (新增)

包含:
1. **产品模块图** — 8 大子系统盒(agent / channels / api / middleware / quality / observability / resilience / persistence)
2. **逻辑架构图** — 三进程:React Frontend / Tauri Shell / Python Backend,内部分层
3. **三条核心数据流概览** — WS 主路径 / 微信通道 / 记忆写入,各自指向 docs/data-flow/ 详细

---

## Task 7 (P2-1): docs/data-flow/ 三张时序图

**Files:**
- `docs/data-flow/ws-main.md` (Mermaid sequenceDiagram)
- `docs/data-flow/wechat-channel.md`
- `docs/data-flow/memory-write.md`

每张图配:
- 标题 + 简介(什么时候走这条路径)
- Mermaid sequenceDiagram
- 关键边界 / 异常路径说明
- 相关源码文件链接

---

## Task 8: 验证

- `git diff --stat SPEC.md CLAUDE.md` 检查改动范围
- 每个新文件 Read 一遍确认格式正确
- grep 文档目录确认旧的 Memory Service 描述已删