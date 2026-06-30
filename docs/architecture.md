# Nexus 架构总览

> **目的**: 给新加入的工程师 / AI agent 一张"产品模块图 + 逻辑架构图 + 数据流入口"的全景图。
> **同步基准**: 代码 2026-07-01,与 `SPEC.md` §架构 对齐。
> **详细时序图**: 见 `docs/data-flow/`(WS / 微信通道 / 记忆写入)。

---

## 1. 产品模块图(子系统分层)

Nexus 按"职责"切成 8 个子系统,各子系统目录对应一组 Python 模块。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Nexus (Python 后端)                            │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ① agent/ ─ DeepAgents 封装                                          │   │
│  │   _agent_builder / _system_prompt / _subagents / _llm_factory /    │   │
│  │   _checkpoint / _backend                                            │   │
│  │   职责: 构造 Agent 实例,挂 middleware 链,管理 checkpoint / store  │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ② middleware/ ─ LLM 调用拦截层(顺序敏感,deepagents AgentMiddleware) │   │
│  │   dynamic_identity ─ 每次 LLM 前注入 [FACT] 块                     │   │
│  │   force_tool      ─ knowledge 类问题强制 yandex_search             │   │
│  │   hitl            ─ PathAwareHITLMiddleware 三态路由                │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ③ quality/ + rubrics/ ─ 质量门(Phase 2)                            │   │
│  │   quality/middleware.py   ─ QualityGateMiddleware 拦截 AGENTS.md 写 │   │
│  │   quality/memory_filter.py ─ MemoryFilter faithfulness ≥ 0.7 才放行│   │
│  │   rubrics/judge.py        ─ RubricJudge 多维度评分                  │   │
│  │   rubrics/repair.py       ─ RepairService 低分自动修复             │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ④ api/ws/ + api/thinking_parser.py ─ WebSocket 协议层               │   │
│  │   ws/auth          ─ token 校验 (hmac.compare_digest) + 心跳        │   │
│  │   ws/streaming     ─ 流式 chunk + thinking_parser 状态机            │   │
│  │   ws/finalize      ─ final / done 帧 + add_message 持久化          │   │
│  │   ws/observability ─ intent 分类 + quality score 集成               │   │
│  │   ws/registry      ─ WS 客户端注册表(广播用)                        │   │
│  │   ws/handlers      ─ 业务编排 + HITL 帧转换                         │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ⑤ channels/ ─ IM 通道抽象层(C5 重构)                                │   │
│  │   base + registry      ─ Channel 基类 + ChannelRegistry             │   │
│  │   gateway              ─ 中央路由:IM 消息 → Agent → 回发 + 广播     │   │
│  │   wechat_* (9 文件)    ─ 微信通道实现                                │   │
│  │   (预留 feishu / telegram)                                           │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ⑥ observability/ + intent/ ─ 观测与意图分类                         │   │
│  │   observability/sink   ─ EventSink(JSONL 轮转,线程安全)            │   │
│  │   observability/handler─ NexusLogHandler(LangChain callback)        │   │
│  │   intent/router        ─ chitchat / knowledge / task / identity     │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ⑦ resilience/ + profiles/ + llm/ + mcp.py ─ 韧性 + 模型适配        │   │
│  │   resilience/stream_guard ─ 流式重试 + 事件计数                     │   │
│  │   resilience/resume       ─ resume_token HMAC + 续传                │   │
│  │   profiles/tier_routing   ─ 弱/强模型 suffix 注册                   │   │
│  │   llm/wrapper             ─ ResilientRunnable                       │   │
│  │   llm/policies / errors   ─ 重试 / 降级策略                         │   │
│  │   mcp.py                  ─ MCP 插件动态加载                        │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                  ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ ⑧ 持久化层 ─ db.py + sessions.py + models.py + routes/*           │   │
│  │   db.py        ─ SQLite + PRAGMA + _ensure_column 自动迁移          │   │
│  │   sessions.py  ─ SessionManager(idempotent / soft-delete / FK 级联)│   │
│  │   models.py    ─ Pydantic(WSMessage / Session / Message / HITL)     │   │
│  │   routes/      ─ REST(/api/models / /api/sessions / /api/messages) │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       持久化(~/.nexus/ + 项目内)                            │
│                                                                             │
│  nexus.db           ─ 5 张表:sessions / messages / quality_scores /         │
│                        resume_tokens / memory_legacy(只读)                  │
│  AGENTS.md (用户级)  ─ deepagents MemoryMiddleware 自动注入                 │
│  models.json        ─ 当前激活模型 + 多模型配置(原子写)                     │
│  logs/              ─ EventSink JSONL 滚动日志                              │
│                                                                             │
│  项目内:                                                                      │
│  nexus/.deepagents/AGENTS.md ─ Nexus 身份规则(禁手编)                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 子系统依赖方向

```
agent ──┬── middleware (深度集成 deepagents AgentMiddleware)
        ├── quality  (拦截 AGENTS.md 写)
        └── api/ws   (调用 agent.astream)

api/ws ──── channels (微信通道广播走 ws/registry)
api/ws ──── resilience (StreamGuard + resume)
api/ws ──── observability (事件写入)
api/ws ──── intent (每条消息跑分类)
api/ws ──── quality (每条消息评分)

channels ── agent (gateway.route_message 调 agent)
channels ── db (sessions / messages 持久化)

agent ────── profiles (HarnessProfile 按 provider:model 挂 suffix)
agent ────── llm (ResilientRunnable 包装)
```

依赖单向,**无循环**。

---

## 2. 逻辑架构图(三进程 + 数据流)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         用户终端(开发者 / 终端用户)                           │
└─────────────────────────────────────────────────────────────────────────────┘
         │                          │                           │
         │ dev mode                 │ dev mode                  │ production
         ▼                          ▼                           ▼
┌─────────────────┐      ┌─────────────────────┐    ┌──────────────────────┐
│ Vite dev server │      │ uvicorn             │    │ Tauri 2 shell        │
│ :30077          │      │ python nexus/       │    │ desktop/src-tauri/   │
│                 │      │   backend/run.py    │    │ - main.rs            │
│ React SPA       │      │ :30000              │    │ - runtime.rs         │
│ (浏览器)        │      │ (FastAPI)           │    │   (sidecar supervisor│
└────────┬────────┘      └──────────┬──────────┘    │   atexit SIGKILL)    │
         │ HTTP/WS                 │                │ - ws_relay.rs        │
         │ /api + /api/ws          │                │   (WS forwarder)     │
         │ (Vite proxy)            │                └──────────┬───────────┘
         │                          │                           │ spawn sidecar
         └────────────┬─────────────┘                           ▼
                      │                              ┌──────────────────────┐
                      │                              │ nexus-runtime        │
                      └─────────────────────────────►│ (PyInstaller 二进制, │
                                                     │  仅含 runtime_main   │
                                                     │  + FastAPI/uvicorn,  │
                                                     │  无 webview)         │
                                                     │ :30000               │
                                                     └──────────┬───────────┘
                                                                │
                                                                ▼
                                          ┌──────────────────────────────────┐
                                          │  FastAPI app (main.py)           │
                                          │                                  │
                                          │  Lifespan:                       │
                                          │   ├─ init_db()                   │
                                          │   ├─ _ensure_agent_async()      │
                                          │   └─ register channels           │
                                          │                                  │
                                          │  Routes:                         │
                                          │   ├─ /api/ws        → ws.py      │
                                          │   ├─ /api/models    → routes/    │
                                          │   ├─ /api/sessions  → sessions   │
                                          │   ├─ /api/messages  → sessions   │
                                          │   ├─ /api/channels/.../bind      │
                                          │   └─ /app/*         → StaticFiles│
                                          └──────────────────────────────────┘
```

### 三进程边界

| 进程 | 角色 | 启动方式 |
|------|------|---------|
| **Vite dev server** (:30077) | 浏览器 SPA + HMR | `cd frontend && npm run dev` |
| **uvicorn FastAPI** (:30000) | 后端 dev 入口 | `python nexus/backend/run.py` |
| **Tauri shell** + sidecar | DMG 生产 | 用户双击 .app 或 `cargo tauri dev` |

Tauri 模式下:
- 主进程 `main.rs` → spawn sidecar `nexus-runtime` (binary)
- sidecar = `nexus/runtime_main.py` 打包出来的轻量 FastAPI/uvicorn 二进制(无 webview 依赖,PyInstaller 友好)
- 主进程通过 `ws_relay.rs` 把前端的 Tauri Channel ↔ 后端 WS 协议转接
- sidecar 死了 → supervisor 自动重启(Rust spawn + atexit SIGKILL 兜底)

---

## 3. 三条核心数据流(概览)

完整时序图见 `docs/data-flow/`,此处只标入口。

### 3.1 WS 主路径 — 用户在 React UI 发消息

```
React ChatArea
   │  WebSocket /api/ws?token=NEXUS_WS_TOKEN
   ▼
FastAPI ws/auth.py          (token 校验 + 心跳)
   │  ws/handlers.py         (业务编排,懒构造 Agent)
   ▼
agent.astream(messages)     (deepagents graph)
   │
   ├─ middleware/dynamic_identity  → inject [FACT] block
   ├─ middleware/force_tool        → 弱模型 knowledge 强制搜
   ├─ middleware/hitl              → 路径感知 HITL 拦截
   └─ middleware/quality_gate      → AGENTS.md 写前 faithfulness 评分
   │
   ▼
LLM API (MiniMax-M3 / Claude / Qwen / DeepSeek)
   │
   ▼  流式 token
ws/streaming.py → thinking_parser 状态机
   │
   ├─ thinking / chunk / tool_call / tool_result  → React 渲染
   ▼
ws/finalize.py → final / done 帧
   │
   └─ db.add_message(role=assistant, content=final)
```

📄 详细: [docs/data-flow/ws-main.md](./data-flow/ws-main.md)

### 3.2 微信通道 — IM 消息异步路径

```
微信用户
   │  IM 推送
   ▼
channels/wechat_channel.py          (Channel 实例)
   │  ChannelMessage(content, user_id, channel_id, ...)
   ▼
channels/gateway.py::route_message  (中央路由)
   │
   ├─ _get_or_create_session(user_key=channel:user)
   │     命中 → 复用;未命中 → DB 查最新 → 创建
   │
   ├─ db.add_message(role=user, content)
   │
   ├─ _call_agent(agent.astream) ──── 走 §3.1 同一条 Agent 链
   │
   ├─ db.add_message(role=assistant, content=response)
   │
   ├─ ch.send_message(回发微信)
   │
   └─ broadcast(channel_message 帧 → 所有 WS 客户端)
```

📄 详细: [docs/data-flow/wechat-channel.md](./data-flow/wechat-channel.md)

### 3.3 长期记忆写入 — 质量门路径

```
LLM 决定"记住 X"(调用 edit_file / write_file 工具)
   │
   ▼
middleware/quality_gate.py::QualityGateMiddleware.awrap_tool_call
   │
   ├─ 目标路径 == ~/.nexus/AGENTS.md 或 nexus/.deepagents/AGENTS.md ?
   │     │
   │     ├─ No  → 放行(交给 PathAwareHITLMiddleware 决定是否 HITL)
   │     │
   │     └─ Yes → quality/memory_filter.py::MemoryFilter.check(value, user_context)
   │              │
   │              ├─ RubricJudge.judge(question, response, tool_calls)
   │              │    评估 faithfulness 维度
   │              │
   │              └─ score ≥ 0.7 ?
   │                   │
   │                   ├─ Yes → 放行(edit_file 真正执行)
   │                   │
   │                   └─ No  → 拦截(LLM 收到 tool error,
   │                            MemoryMiddleware 不会持久化)
```

📄 详细: [docs/data-flow/memory-write.md](./data-flow/memory-write.md)

---

## 4. 关键设计点速查

| 设计 | 位置 | 原因 |
|------|------|------|
| WS 跨线程桥接 | `api/ws/*.py` callback 内 `asyncio.run_coroutine_threadsafe` | DeepAgents callback 不能 await |
| Agent 懒构造 | `main.py::_ensure_agent_async` + `_agent_ready_event` | `/health` 在 Agent 构造期间也能 200,DMG 启动不被卡住 |
| Token 比较 | `hmac.compare_digest` | 防时序攻击 |
| Stream 状态机 | `api/thinking_parser.py` | `<thinking>` 标签可能被截断在 chunk 边界,需 hold partial |
| Memory 不入库 | deepagents 自动注入 `<agent_memory>` | v0.1 自定义 `MemoryService` 已废弃 |
| 质量门 | `quality/middleware.py` + `quality/memory_filter.py` | 拦截 LLM 写 AGENTS.md,防幻觉污染长期记忆 |
| Static 前端 | `app.mount("/app", StaticFiles)` | DMG 内零端口前端,只起一个 uvicorn |
| 断点续传 | `resume_tokens` 表 + `last_event_id` | 网络抖动重连不丢消息 |
| Tauri sidecar | `desktop/src-tauri/src/runtime.rs` | atexit SIGKILL 兜底,主进程任何路径退出都先杀 sidecar |

---

## 5. 相关文档

- [SPEC.md](../SPEC.md) — 完整技术规格(DB schema / WS 帧 / 中间件链)
- [CLAUDE.md](../CLAUDE.md) — AI 协作入口 + 关键约束
- [docs/data-flow/](./data-flow/) — 三条核心数据流时序图
- [docs/superpowers/plans/](./superpowers/plans/) — 历史计划文档
- [docs/operations/](./operations/) — 运维文档(quality / logging / signing)