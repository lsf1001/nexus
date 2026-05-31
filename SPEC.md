# Nexus 技术规格

## 架构

```
┌─────────────┐         HTTP/WebSocket        ┌─────────────┐
│   React     │ ◄─────────────────────────────► │   FastAPI   │
│   Frontend  │                              │   Backend   │
│   (:30000)  │                              │   (:30000)  │
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
nexus/
├── frontend/           # React SPA
│   ├── src/
│   │   ├── components/   # ChatArea, Sidebar, ChatBubble...
│   │   ├── store/        # Zustand 状态
│   │   ├── types/        # TypeScript 类型
│   │   └── App.tsx
│   └── vite.config.ts
├── nexus/
│   ├── backend/        # FastAPI 后端
│   │   ├── main.py     # 入口 + API + WebSocket
│   │   ├── agent.py    # DeepAgents 封装
│   │   ├── sessions.py # SessionManager
│   │   ├── memory.py   # MemoryService + EvolutionService
│   │   ├── db.py       # SQLite
│   │   └── channels/   # wechat, base, registry
│   └── cli/            # CLI (Typer)
│       ├── main.py
│       └── daemon/     # launchd, systemd
└── tests/             # pytest
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
- `create_subagents()` - 子代理（code_writer, researcher）
- `get_llm()` - LLM 实例创建

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

-- 记忆
memories(id, session_id, category, memory_type, key, value, created_at)
```

## CLI

```bash
nexus install    # launchd/systemd
nexus start/stop/restart
nexus status/logs
nexus uninstall
nexus setup/doctor
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIMAX_API_KEY` | - | API Key |
| `MINIMAX_API_BASE` | https://api.minimaxi.com/v1 | 端点 |
| `NEXUS_WS_TOKEN` | nexus-default-token | WebSocket 认证 |
| `NEXUS_PORT` | 30000 | 端口 |
| `NEXUS_ENABLE_MCP` | true | 启用 MCP |

---

*最后更新: 2026-06-01*