# Nexus 日志与可观测性

> **目标**:在不开 IDE / 不接 LangSmith 的前提下,从日志还原一次 chat 的完整轨迹。
> **核心设计**:JSONL 文件 + 4 个产品事件 + env 三档配置 + LangChain callback 通道复用。

---

## 快速上手

### 默认(text 模式,开发友好)

```bash
.venv/bin/python -c "import uvicorn; uvicorn.run('nexus.backend.main:app', ...)"
# 日志写: ~/.nexus/logs/nexus.log(10MB 轮转,保留 5 份)
```

### 生产(json 模式)

```bash
NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/var/log/nexus/nexus.log ./Nexus.app/...
```

### 排障(verbose,看 LangGraph 全链路)

```bash
NEXUS_LOG_FORMAT=text NEXUS_AGENT_VERBOSE=1 PYTHONUNBUFFERED=1 ./.venv/bin/python -c "import uvicorn; ..."
# 额外挂 StdOutCallbackHandler,stdout 实时打印 > Entering new ... chain
```

---

## 环境变量

| 变量 | 默认 | 取值 | 说明 |
|---|---|---|---|
| `NEXUS_LOG_FORMAT` | `text` | `text` \| `json` | text = uvicorn 风格;json = 每行 JSON |
| `NEXUS_LOG_FILE` | `~/.nexus/logs/nexus.log` | 任意路径 | 父目录不存在会自动创建 |
| `NEXUS_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | root logger 级别 |
| `NEXUS_AGENT_VERBOSE` | 未设 | `1` | 额外挂 `StdOutCallbackHandler`,stdout 实时打印 LangGraph 链路 |

**轮转**:固定 10MB × 5 份(代码内常量)。后续若需可调,再加 env。

---

## 事件字典

### 产品事件(每次 chat 必出,4 条)

| 事件 | 触发时机 | 必填字段 | 可选字段 |
|---|---|---|---|
| `chat.start` | 收到 user 消息,即将分发 | `session_id` `message_id` `content_len` | — |
| `intent.classified` | 意图分类完成 | `session_id` `message_id` `intent` `latency_ms` | `fallback` |
| `quality.verdict` | 质量门评分完成 | `session_id` `message_id` `verdict` `scores` `repair_attempted` | — |
| `chat.end` | 流结束(成功 / 异常) | `session_id` `message_id` `chunks` `duration_ms` `retry_count` | `intent` `verdict` `error_code` |

> `chat.end` 当前只在正常完成分支(stream_completed=True、发了 `done` 帧后)emit;
> 澄清挂起 / 错误流分支不发,后续若需覆盖补发可扩展 `handle_websocket`。
>
> `chunks` 当前是 `len(response_text) // 16` 估算值(精确 chunk count 在 `_run_agent_streaming` 内部);
> 后续若需精确值,扩展该函数返回 `chunk_count` 即可。

### LangChain 内部事件(NexusLogHandler 转写,仅供调试)

| 事件 | 来源 | 字段 |
|---|---|---|
| `llm.start` | `on_llm_start` | `model` `prompt_chars` `run_id` |
| `llm.end` | `on_llm_end` | `run_id` `duration_ms` `prompt_tokens` `completion_tokens` `total_tokens` |
| `tool.start` | `on_tool_start` | `tool` `input_chars` `run_id` |
| `tool.end` | `on_tool_end` | `run_id` `duration_ms` |
| `chain.start` / `chain.end` | `on_chain_*` | `chain` `run_id` `duration_ms` |

> LangChain 事件在生产观测中也开,但默认 `NEXUS_LOG_FORMAT=json` 时按 INFO 级落盘。
> 想只看产品事件:`jq 'select(.event | startswith("chat."))'`。

---

## 常用查询

### 今日所有 REJECT

```bash
jq 'select(.event=="quality.verdict" and .verdict=="REJECT")' ~/.nexus/logs/nexus.log
```

### 按 session 聚合 chat 耗时

```bash
jq 'select(.event=="chat.end") | {session_id, duration_ms}' ~/.nexus/logs/nexus.log | \
  jq -s 'group_by(.session_id) | map({session: .[0].session_id, total_ms: (map(.duration_ms) | add)})'
```

### 工具调用排行

```bash
jq 'select(.event=="tool.start") | .tool' ~/.nexus/logs/nexus.log | sort | uniq -c | sort -rn
```

### intent 分布

```bash
jq 'select(.event=="intent.classified") | .intent' ~/.nexus/logs/nexus.log | sort | uniq -c
```

---

## DMG 桌面端

Electron 主进程拉起 PyInstaller 打包的 backend(`./Nexus.app/Contents/Resources/nexus-backend/nexus-backend`)。
日志路径:

- **默认**: `/Users/<user>/.nexus/logs/nexus.log`
- **重定向**: 设置 `NEXUS_LOG_FILE` 环境变量(在 Electron `desktop/src/backend.ts` 启动 backend 时 export)

主进程建议在 SetupView 加一行"打开日志文件夹"按钮,直接 `open ~/.nexus/logs`。

---

## 故障排查

### 看不到 JSON 行

1. 确认 `NEXUS_LOG_FORMAT=json` 已设
2. 确认日志文件路径可写(`~/.nexus/logs/` 父目录)
3. `tail -F` 实时看,不要 `cat`(后者会一次性读完整文件)

### verbose 模式没看到 LangGraph chain 输出

1. 确认 `NEXUS_AGENT_VERBOSE=1`
2. 确认 stdout 没被重定向到不可读位置(PyInstaller frozen 模式下可能 stderr-only)
3. 设 `PYTHONUNBUFFERED=1`,否则 Python print buffer 会延迟

### 日志文件过大

- 10MB 自动轮转,5 份上限 = 60MB 上限
- 若仍嫌大:`NEXUS_LOG_LEVEL=WARNING` 减少 INFO 量
