# WS 主路径时序图

> **场景**: 用户在 React 前端 ChatArea 发送一条消息,后端 Agent 流式响应,前端实时渲染,最终落库。
> **入口**: `frontend/src/hooks/useWebSocket.ts`(dev)或 `useTauriWs.ts`(DMG,Rust relay)
> **后端入口**: `nexus/backend/api/ws/handlers.py::handle_websocket`

## 1. 完整时序

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant UI as React ChatArea
    participant Hook as useWebSocket/useTauriWs
    participant FA as FastAPI ws/handlers.py
    participant Auth as ws/auth.py
    participant Init as main.py::_ensure_agent_async
    participant Mid as middleware/* 链
    participant LLM as LLM API
    participant SP as ws/streaming.py
    participant TP as thinking_parser.py
    participant Fin as ws/finalize.py
    participant DB as SQLite (nexus.db)

    User->>UI: 输入 "BTC 还能涨吗"
    UI->>Hook: send({content, session_id?})
    Hook->>FA: WebSocket /api/ws?token=xxx

    rect rgb(245, 245, 245)
        Note over FA,Auth: ① 鉴权 + 心跳
        FA->>Auth: verify_token(token)
        Auth-->>FA: hmac.compare_digest 通过
        FA->>FA: websocket.accept()
    end

    rect rgb(245, 245, 245)
        Note over FA,Init: ② 懒构造 Agent(首启 10-30s)
        FA->>Init: _ensure_agent_async(app)
        Init-->>FA: 启动后台线程 _run_init_and_signal
        FA->>FA: await _agent_ready_event.wait(timeout=60s)
    end

    rect rgb(245, 245, 245)
        Note over UI,FA: ③ 创建会话(若新)
        FA-->>UI: session_created 帧(session_id)
    end

    UI->>FA: WSMessage({content: "BTC 还能涨吗"})

    rect rgb(230, 245, 230)
        Note over FA,LLM: ④ Agent 流式推理
        FA->>Mid: build_prompt(messages) + astream
        Mid->>Mid: dynamic_identity 注入 [FACT] 块
        Mid->>Mid: force_tool 识别 knowledge 类
        Mid->>LLM: POST /v1/chat/stream (含工具列表)
        LLM-->>Mid: 流式 token
        Mid-->>SP: chunk
        SP->>TP: feed(content)
        TP-->>SP: [("thinking", "...") | ("chunk", "...")]
    end

    rect rgb(230, 245, 230)
        Note over SP,UI: ⑤ 流式推送(主路径帧)
        SP-->>UI: thinking 帧(<thinking>...</thinking>)
        SP-->>UI: chunk 帧(Markdown 文本)
        SP-->>UI: tool_call 帧(若 LLM 调用工具)
        SP-->>UI: tool_result 帧(工具执行结果)
    end

    rect rgb(230, 230, 245)
        Note over LLM,SP: ⑥ 工具调用循环(可选)
        SP->>Mid: 工具结果回灌
        Mid->>LLM: 继续 astream
        LLM-->>Mid: 更多 chunk
        Mid-->>SP: chunk
        SP-->>UI: chunk 帧
    end

    rect rgb(245, 230, 230)
        Note over Fin,DB: ⑦ 收尾 + 落库
        Fin->>FA: 累积完整文本,去 <thinking> 标签
        FA->>DB: add_message(session_id, role=assistant, content=final)
        FA-->>UI: final 帧(完整文本)
        FA-->>UI: token_usage 帧(可选)
        FA-->>UI: done 帧(回合结束)
    end

    UI->>User: 流式渲染完成
```

## 2. 关键边界 / 异常路径

| 场景 | 行为 | 帧类型 |
|------|------|--------|
| Token 错误 / 缺失 | `websocket.close(code=4001, reason="未授权")` | (无帧) |
| Agent 懒构造 60s 超时 | 走 `agent_unavailable` 错误路径,不阻塞握手 | `error` |
| LLM 流中断 | `resilience/stream_guard.py` 按 `policies.retry` 重试 N 次 | 期间不推送帧,重试成功后继续 chunk |
| LLM 完全失败(重试用尽) | 推 `error` 帧,`error_code=llm_unavailable` | `error` |
| 用户输入触发澄清 | Agent 调 `ask_user` 工具 → 中断 astream → WS 推澄清帧 → 前端弹窗 | `clarification_request` |
| Agent 要写文件触发 HITL | `middleware/hitl.py::PathAwareHITLMiddleware` 抛 `GraphInterrupt` → 转 `confirmation_request` 帧 → 前端按钮 → 回 `confirmation_response` 帧 → `Command(resume=...)` 续流 | `confirmation_request` / `confirmation_response` |
| WS 断开后重连 | 客户端带 `resume_token` query → `ws/auth.py` 校验 → `ws/resume.py` 从 `resume_tokens.last_event_id` 续推 | `resume_ack` + 重放 |
| resume_token 失效 | 推 `invalid_resume_token` 帧,客户端需建新会话 | `invalid_resume_token` |

## 3. 帧序列约定

完整 18 种帧定义见 `frontend/src/types/index.ts::StreamEvent union`。

主路径顺序(成功):
```
session_created → thinking* → chunk* → (tool_call → tool_result → chunk*)* → final → done
```

辅帧(可能穿插):
- `token_usage` — 在 done 前或长流中
- `stats` — 失败/降级时携带 `retries` / `fallbacks` / `events_emitted`
- `error` — 终态,不会再发后续帧

## 4. 关键源码文件

| 层 | 文件 | 职责 |
|----|------|------|
| 前端 hook | `frontend/src/hooks/useWebSocket.ts` | 浏览器 dev 模式直连 WS |
| 前端 hook | `frontend/src/hooks/useTauriWs.ts` | Tauri DMG 模式(Rust relay 转发) |
| 鉴权 | `nexus/backend/api/ws/auth.py` | `hmac.compare_digest` + 心跳 |
| 业务编排 | `nexus/backend/api/ws/handlers.py` | `handle_websocket` 主循环 |
| 流式 | `nexus/backend/api/ws/streaming.py` | chunk / thinking / tool_call 帧生成 |
| 状态机 | `nexus/backend/api/thinking_parser.py` | `<thinking>` 标签跨 chunk 边界处理 |
| 收尾 | `nexus/backend/api/ws/finalize.py` | final / done 帧 + add_message 持久化 |
| 落库 | `nexus/backend/db.py::add_message` | SQLite 写 messages 表 + 更新 sessions.updated_at |
| 中间件 | `nexus/backend/middleware/*.py` | dynamic_identity / force_tool / hitl 链 |
| 韧性 | `nexus/backend/resilience/stream_guard.py` | 流式重试 |
| 续传 | `nexus/backend/resilience/resume.py` | resume_token HMAC + 续推 |

## 5. 性能 / 资源要点

- **Agent 懒构造**: 首条消息才有 10-30s 等待,后续消息几乎 0 延迟
- **busy_timeout=30s**: db.py 启用,抗 aiosqlite 写锁等待
- **StreamGuard**: 单 chunk ≤ N ms,长 chunk 拆分推送避免前端卡顿
- **thinking_parser**: hold partial 标签,flush 时兜底,确保不丢字
- **token_usage 帧**: 长对话触发(>8K tokens),提示用户即将超限
---

## 6. 相关文档

- [architecture.md §3.1](../architecture.md#31-ws-主路径--用户在-react-ui-发消息) — 概览
- [SPEC.md §WebSocket](../SPEC.md) — 完整 18 种帧定义 + ws/ 包结构
- [wechat-channel.md](./wechat-channel.md) — Agent 处理部分复用本图 §④
