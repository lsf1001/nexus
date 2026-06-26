# Nexus 技术规格

## 架构

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
                    └─────────────┘          └─────────────┘          └─────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 前端 | React + TypeScript + Vite + Tailwind CSS + Zustand |
| 后端 | FastAPI + DeepAgents + SQLite |
| 模型 | MiniMax / DeepSeek / Qwen (OpenAI SDK 兼容) |
| 守护 | launchd (macOS) / systemd (Linux) |

## 项目结构

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
│   └── cli/            # CLI (Typer)
│       ├── main.py
│       └── daemon/     # launchd, systemd
└── tests/             # pytest (后端)
```

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

⚠️ **execution backend 警告**:LocalShellBackend / LangSmithSandbox / ContextHubBackend 让
LLM 可以执行 shell / 远程代码。deepagents 0.6.8 的 FilesystemMiddleware 不支持同时配
permissions 和 execution backend(框架会主动禁用 permissions)。生产建议禁用,
本地开发 / CI 测试按需开启。

### WebSocket (main.py)

- `/api/ws` - 实时对话端点
- 流式响应：`thinking` → `chunk` → `final` → `done`
- 支持多客户端

### 微信通道 (channels/wechat.py)

- 二维码登录
- 消息回调处理
- 自动会话创建

## 数据库

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

迁移：`db.py` 通过 `_ensure_column()` 兼容老库（缺列则 `ALTER TABLE ADD COLUMN`），无需手工脚本。

## CLI

2026-06 清理：产品不再提供 CLI（`nexus/cli/` 整包删除）。终端用户走 macOS DMG APP（`/Applications/Nexus.app`，Electron 拉起后端），开发者从 git clone 走源码直跑：

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

最近一轮稳定性修复（已通过 83 项 E2E 验证）：

- **PRAGMA 启用**：`db.py` 在连接建立时执行 `foreign_keys=ON`、`journal_mode=WAL`、`synchronous=NORMAL`，避免跨表引用失败和断电丢数据
- **模型配置原子写**：`models_config.save_models()` 走 `tmp + fsync + os.replace` 流程，写失败不污染原文件
- **REST 状态码语义**：`routes/model_config.py` 使用 `HTTPException` + 标准状态码（404/409/400/201/422），不再返回 `{"success": false}`
- **CORS 白名单**：`NEXUS_ALLOWED_ORIGINS` 控制允许来源；dev 默认通配，生产可收紧
- **BM25 增量缓存**：`MemoryService` 按 `(id, key, value)` 签名复用分词结果，未变化文档不重算
- **用户消息去重**：连续相同 `content` 在 2s 内只触发一次 LLM 调用，避免误触重发
- **WS 跨线程桥接**：流式回调在子线程中通过 `asyncio.run_coroutine_threadsafe` 投递回事件循环，不阻塞通道

---

*最后更新: 2026-06-02*
