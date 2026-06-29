# Changelog

Nexus 项目的所有重要变更都记录在此文件。本文件格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased] — 修复 model identity 串味:system_prompt 改用 middleware 实时注入

### Problem

用户反馈"标题显示 MiniMax-M3,LLM 答 agnes-2.0-flash,你设计的逻辑不对吧"。
具体场景:DMG 启动时 active=agnes,用户通过改 `~/.nexus/models.json` 切到
MiniMax-M3(没走 `POST /api/models/switch` 重建 agent),UI 标题栏立刻
反映新模型(`/api/model` 端点读 models.json 实时),但 LLM 收到的
system_prompt **仍然含旧 agnes** → LLM 自报"agnes-2.0-flash"。

### Root Cause

`_build_system_prompt` 把"当前驱动模型 = X"作为字符串常量塞进 system prompt,
**在 `create_agent()` 阶段只拼一次**。agent 是单例(lifespan 懒构造),
构造完成后 system_prompt 是 immutable baked string。`POST /api/models/switch`
会触发 `create_agent_with_model` 重建,但用户从 UI / 终端 / 第三方工具
直接改 `models.json` **不会**重建 agent → 标题栏(`/api/model` 端点)
和 LLM 回答的数据源不同步。

第一轮 fix (本 Unreleased 上一个 entry) 用 `cache_key = "model@active_name"`
试图让 prompt 在切换时重算 → 仍**没有**解决根本问题:active_name 改变
时,如果新一次 LLM 调用走的是同一个 agent 实例的缓存路径,prompt 还是会
用缓存的老值(缓存不是永远 100% miss)。

### Changed (第三轮重构 · 2026-06-29)

把"当前驱动模型信息"从"prompt 字符串里的死字面量"挪到"每次 LLM 调用前
实时注入的 middleware",从根上消除缓存滞留。

- **`nexus/backend/middleware/dynamic_identity.py`** (新增,121 行):
  - `dynamic_identity_middleware` 用 LangChain `@wrap_model_call` 装饰器
    实现,挂在 `create_deep_agent(middleware=[..., dynamic_identity_middleware])`
  - `wrap_model_call` 钩子每次 LLM 调用前**实时**调
    `get_active_model_info()` 读 `~/.nexus/models.json`,把
    `[FACT · 当前驱动模型 · 运行时实时注入]` 块 prepend 到
    `request.system_message.content` 的最前面
  - **async 签名**:deepagents 的 `agent.astream(...)` 走 async 路径,同步
    `wrap_model_call` 在 async 上下文里会抛 `NotImplementedError:
    Asynchronous implementation of awrap_model_call is not available`
    (E2E 2026-06-29 暴露)。函数用 `async def`,装饰器自动注册
    `awrap_model_call`
  - **不**缓存 FACT 块字符串 —— 缓存就是 bug 来源。每次都重算。
  - `system_message` 为 `None` 的防御性分支(理论上不会触发,只兜底)

- **`nexus/backend/agent.py::_build_system_prompt` 改写**:
  - 删 `[FACT · 当前驱动模型]` 块(由 middleware 注入,不在这里拼)
  - 删 `当前驱动模型: {driver_name}` 这类 hardcode(在【身份】段)
  - 加 `【驱动模型信息 · 由 middleware 注入】` 段,告诉 LLM "FACT 块
    来自 DynamicIdentityMiddleware,直接用里面的 name / vendor 答"
  - 删所有 `{driver_name}` / `{driver_vendor}` f-string 插值,函数
    **与激活模型完全无关**

- **`nexus/backend/agent.py::get_system_prompt` 缓存简化**:
  - `_CACHED_PROMPT` 从 `dict[str, str]` (key = `model_name@active_name`)
    改为单 bucket (`_CACHED_PROMPT["__default__"]`)
  - 旧方案的 `model@active_name` 维度是为了"切模型时强制重算 prompt";
    现在 FACT 已不在 prompt 字符串里 → 缓存滞留问题从根上消失,
    不需要分桶

- **`nexus/backend/agent.py::create_agent` middleware 挂载**:
  - `middleware=[quality_gate]` → `middleware=[quality_gate, dynamic_identity_middleware]`
  - dynamic_identity 在 LLM 调用**前** mutate system_message(quality_gate
    只拦截 tool_call,顺序无影响)

- **`nexus/backend/middleware/__init__.py`** (新增):包级 docstring 说明
  这个包存在的原因(middleware 拿不到 graph state,只能改 ModelRequest
  再透传;middleware 之间互不耦合,各跑各的)

### Added

- **`tests/test_agent_memory.py::TestBuildSystemPromptIsModelAgnostic`**
  (5 个测试):验证 `_build_system_prompt` 输出与激活模型无关 —
  - `test_prompt_does_not_bake_active_model_name` — prompt 不应再含具体模型名
  - `test_prompt_mentions_middleware_fact_block` — prompt 必须说明 FACT 块由 middleware 注入
  - `test_prompt_mentions_get_model_info_tool` — 工具仍然注册
  - `test_prompt_is_model_independent` — 切换 active model 后 prompt **完全不变**
  - `test_other_rules_kept` — 重构后产品层规则段保留
- **`tests/test_agent_memory.py::TestDynamicIdentityMiddleware`** (3 个测试):
  - `test_middleware_injects_fact_block_with_active_model` — 系统消息 prepend FACT 块
  - `test_middleware_reads_models_json_freshly` — 切换 active model 后**下次调用立即反映**
  - `test_middleware_handles_missing_active_model` — 无 active 模型时走降级措辞
- **`tests/test_agent_memory.py::TestCreateAgentWiresDeepAgentsMemory::test_middleware_kwarg_contains_dynamic_identity`** —
  契约:dynamic_identity_middleware 必须出现在 `create_deep_agent` 的
  `middleware=` 列表里(破了 → LLM 收不到 FACT → 串味回归)

### Verified

- `ruff check nexus/`:All checks passed
- `ruff format --check nexus/`:0 diff
- `pytest tests/test_agent_memory.py`:22 passed
- `pytest tests/`:549 passed, 12 skipped, 2 failed(基线 537 + 新 12 测试,
  零回归。2 失败全在 `tests/test_e2e_features.py`,需要 backend 跑起来 +
  真实 LLM API key,pre-existing 基础设施依赖,跟本次改动无关)
- E2E WS(同 server 实例,不重启):
  - active = agnes-2.0-flash → LLM 答 "我是 Nexus,由 agnes-2.0-flash 驱动 ... agnes-2.0-flash 由 agnes-ai 提供"
  - 改 models.json 切到 MiniMax-M3 → 下一轮 LLM 答 "我是 Nexus,由 MiniMax-M3 驱动 ... MiniMax-M3 由 MiniMax 提供"
  - **不重启 backend、不重建 agent**,回答立即反映新值,UI 标题栏永远一致

### Notes

- **为什么必须 async**:`@wrap_model_call` 装饰器会根据被装饰函数是
  sync 还是 async 自动注册 `wrap_model_call` 或 `awrap_model_call`。
  deepagents 的 `agent.astream()` 走 async 路径,如果只提供 sync 版本,
  第一次 LLM 调用会抛 `NotImplementedError`,ResilientRunnable 重试 2 次
  后给用户报 "重试 2 次后仍失败: NotImplementedError: Asynchronous ..."。
  函数改 `async def` 之后,装饰器只注册 `awrap_model_call`,无副作用。
- **数据流单一性**:`models.json` 仍然是唯一权威。middleware 在每次
  LLM 调用前重读一次,纯 IO 是 `json.loads(6KB)`,< 1ms,可忽略。
- **不再需要 `cache_key = "model@active_name"`**:这种 cache 维度是
  第二轮的妥协方案,本质是把"动态数据"塞进"静态缓存"的反模式。
  现在的架构是"prompt 字符串 = 静态,FACT 块 = 动态注入",从根本上
  让两层数据各走各的路径,缓存问题不存在了。

---

## [Unreleased] — 模型身份改用实时注入(不再硬编码,不再瞎答训练记忆)

### Problem

用户反馈"用的什么模型 应该真实获取模型的信息 而不是硬编码"。
本轮迭代解决 2026-06-29 暴露的两个 LLM 自我介绍答错场景:

1. **场景 A — 硬编码失效**:之前 fix 把 `model_name` 字符串拼进
   `f"基于 {driver_label} 打造"` 这种 prompt 模板字面量 → 启动时快照一次
   之后,用户切换模型若未走 `POST /api/models/switch` 重建 agent,
   prompt 还显示老模型,用户被误导。
2. **场景 B — LLM 不调工具**:试图改成"prompt 引导 LLM 必须先调
   `get_model_info` 工具拿真实数据" → E2E 验证(问"你用的什么模型"):
   - 当前 active = agnes-2.0-flash,训练数据里有 → LLM 凭记忆答对
     (Sapiens AI / agnes-2.0-flash),**工具 0 次调用** — 看似 OK
     但完全没"实时获取"
   - 当前 active = 其他冷门模型,训练数据里没有 → LLM **瞎答**
     "我使用的是 Qwen 模型,由阿里云(Alibaba Cloud)开发",**完全没看
     prompt 指令** — 提示词形同虚设

### Root Cause

- 把"模型身份"当作字符串常量塞进 prompt 模板 → 任何"数据源必须活"的
  保证都依赖外部机制,内生不可靠。
- 把"必须调工具"当 soft rule → LLM 训练抗性让 soft rule 失效。

### Changed

- **`nexus/backend/agent.py::_build_system_prompt` 实时读 active model**:
  - 函数体里调 `get_active_model_info()` 从 `~/.nexus/models.json` 实时读
    name / vendor,拼进 prompt 顶部 `[FACT · 当前驱动模型]` 块
  - 数据源是**单一**的(models.json),切换模型后下一轮构造自动反映新值
  - `get_system_prompt` cache key 改为 `f"{model_name}@{active_name}"` →
    切换激活模型后旧 cache 立刻失效,新 prompt 重新读盘生成
- **`nexus/backend/models_config.py::infer_vendor`** (新增):从 `api_base`
  URL 域名推断 vendor(MiniMax / agnes-ai / OpenAI / Anthropic),未知走
  "未知厂商"兜底
- **`nexus/backend/models_config.py::get_active_model_info`** (新增):返回
  `{name, vendor, api_base, temperature, is_active}` 完整 dict
- **`nexus/backend/tools.py::get_model_info`** (新增 `@langchain_tool`):
  每次调用都重新读 `~/.nexus/models.json` 返回实时 JSON,挂进 `TOOLS`
  列表,LLM 可主动调(展示实时数据 / 排障场景)
- **prompt 强约束**:forbidden 块加 "任何跟 FACT 块里 name/vendor 不一致的
  版本" → LLM 想答错都难

### Verified

- `pytest tests/test_agent_memory.py`:18 passed(含 5 个新契约 + 3 个 tool 注册测试)
- `pytest tests/ -q --ignore=tests/test_e2e_features.py`:534 passed
- E2E 验证(dev uvicorn + WS,active = agnes-2.0-flash):
  问"你用的什么模型" → LLM 答:
  > 我是 Nexus,由 agnes-2.0-flash 驱动。Nexus 是夜小白科技有限公司基于
  > agnes-2.0-flash 模型打造的 AI 智能助理。agnes-2.0-flash 由 agnes-ai 提供。
  答对 model name + vendor + 公司 + 产品名,精确按 prompt 模板输出。

### Notes

- **数据源单一**:`~/.nexus/models.json` 是唯一权威。`api_base` 域名
  映射 vendor: `apihub.agnes-ai.com → agnes-ai`, `api.minimaxi.com → MiniMax`。
  新增 vendor 厂商需要更新 `_VENDOR_BY_HOST` 常量。
- **cache 策略**:cache key = `"{model_name}@{active_name}"`,双维度保证
  切换时立即失效。
- **为什么还需要 `get_model_info` 工具**(不只靠 prompt 注入):
  - 用户问"给我看实时数据" → LLM 调工具展示当前 model info
  - 调试场景:用户报告"模型没切换" → 调工具对账 models.json vs 实际 driver

---

## [Unreleased] — 修复 LLM 自我介绍答错(切到 Agnes 后还说 MiniMax-M3)

### Problem

用户切到 agnes-2.0-flash 后,在 Nexus 里问"你用的什么模型",
LLM 仍然回答"我用的是 MiniMax-M3 模型,由 MiniMax 公司开发"。
原因是 system prompt 的【身份】段硬编码了产品身份,没有告诉
LLM 当前实际驱动模型是哪个,所以 LLM 只能瞎猜 / 退回训练时的默认。

### Root Cause

`_build_system_prompt()` 写死的身份段:
> 你是 Nexus,夜小白科技有限公司开发的 AI 智能助理。

这条 prompt 不含任何关于"当前驱动模型"的信息。LLM 被问"你用的什么
模型"时没有任何上下文 introspection,只能默认回答训练时常见的 MiniMax-M3。

### Changed

- **`nexus/backend/agent.py::_build_system_prompt` 接受 ``model_name``**:
  - 签名 `_build_system_prompt() -> _build_system_prompt(model_name: str = "")`
  - 身份段改为"夜小白科技有限公司基于 {driver_label} 打造的 AI 智能助理"
  - 回答规则第 2 条改为"问你是谁 / 你用的什么模型,必须回答'我是 Nexus,由 {driver_label} 驱动'"
  - 空字符串兜底为"当前驱动模型"占位措辞(防御性,不阻塞启动)
- **`get_system_prompt` / `reload_system_prompt` 按 model_name 分桶缓存**:
  - `_CACHED_PROMPT` 由 `str | None` 改为 `dict[str, str]`,键 = model_name(`""` 用 `"__default__"` 占位)
  - `reload_system_prompt("")` 清空整个缓存;`reload_system_prompt("agnes-2.0-flash")` 只清该桶
  - WHY:模型切换瞬间旧 agent 仍持有旧 system_prompt,分桶避免"切到 agnes 还显示 minimax" 串味
- **`create_agent` 把 model_name 传给 get_system_prompt**:
  - `system_prompt=get_system_prompt(model_name or CONFIG.get("model_name", ""))`
  - `model_name` 参数缺省时回退到 `CONFIG["model_name"]`,跟 `get_llm` 默认对齐

### Added

- **`tests/test_agent_memory.py::TestBuildSystemPromptIsModelAware`** — 4 个回归测试:
  - `test_identity_section_includes_model_name_agnes` — agnes 名进身份段
  - `test_identity_section_includes_model_name_minimax` — MiniMax 名进身份段
  - `test_identity_section_changes_with_model_name` — 两个 model_name 产出不同 prompt(防"挂羊头卖狗肉"反模式)
  - `test_other_rules_kept_when_model_name_provided` — 加 model_name 参数后其他规则段不丢

### Verified

- `ruff check nexus/ tests/`:All checks passed
- `ruff format --check nexus/ tests/`:122 files already formatted
- `pytest tests/test_agent_memory.py`:14/14 通过(原 10 + 新 4)
- `pytest tests/`:541 passed,2 pre-existing e2e 失败(infra 依赖,非本次回归)

### Notes

- **完整标准话术示例**(active = MiniMax-M3):
  > 我用的是 MiniMax-M3 模型,由 MiniMax 公司开发。我是 Nexus,夜小白科技有限公司基于这个模型打造的 AI 智能助理。
- **完整标准话术示例**(active = agnes-2.0-flash,假设其 vendor 未知):
  > 我用的是 agnes-2.0-flash 模型。我是 Nexus,夜小白科技有限公司基于这个模型打造的 AI 智能助理。
- vendor 公司归属字段需要查模型元数据,未知就只说模型名(可省略"由 X 公司开发")。

---

## [Unreleased] — 修复切到 Agnes 后 26s 转圈 + 思考过程不显示

### Problem

用户反馈:切换到 Agnes 模型后,前端一直 spinner 转圈,也不显示思考过程。

实测(`~/.nexus/logs/nexus.log` 2026-06-28 21:18):
  | 时点 | 事件 | 累计 |
  |---|---|---|
  | 21:18:05 | 用户发"hi" | 0s |
  | 21:18:22 | intent 分类返回 | **+16.8s**(超时 8s 配置未生效) |
  | 21:18:33 | LLM 流结束 | +28.3s |
  | 21:18:33 | 客户端 code=1006 断开 | (用户放弃等待) |

对比:MiniMax intent 4s + LLM 2.6s = 7s 收到首帧;Agnes 路径全链路 ≥ 26s 零反馈,用户体感"卡死"。

### Root Cause (三层叠加)

1. **chunk 全部缓存**:`ws.py::_run_agent_streaming` 把 `on_chat_model_stream` 每个 chunk 累加到 `full_response`,等 LLM 跑完才按 16 字符切碎发出去。期间前端零帧。
2. **intent 分类无心跳**:`_classify_and_record` 在调 LLM 分类前不发任何 WS 帧;分类阻塞 16s+ 期间,前端 `isLoading=true` 但收不到任何东西。
3. **`<thinking>` 标签流末抽取**:原 `re.findall` 在 `full_response` 上提取 — LLM 不主动输出 `<thinking>` 标签时,UI 永远看不到"思考过程"。
4. **额外**:`asyncio.wait_for(8)` 对 agnes httpx connection 挂起不可靠,cancel 未传播,实际 latency 16821ms。

### Changed

- **`nexus/backend/api/ws.py::_run_agent_streaming` 实时 emit**:
  - 删 `full_response += content` 缓存 + 16 字符后处理切块 + `re.findall` thinking 抽取
  - `on_chat_model_stream` 每 chunk 立即 `parser.feed(content)` → 每个 `(kind, text)` 立刻 `send_json`
  - `on_chat_model_end` 兜底走同路径(非流式 LLM,带 `not emitted_chunk_text` 守卫防 mock 双发)
  - 流末 `parser.flush()` 把残留 hold / thinking 全部发完
  - `final` 帧改用实时累积的 `emitted_chunk_text`(替换 `full_response` 字符串)
  - `token_usage` / `done` 帧逻辑保持不变(下游契约不动)
- **`nexus/backend/api/ws.py::_classify_and_record` 加心跳**:
  - 函数签名加 `websocket` + `last_event_id: int = 0` 参数
  - 入口先发一个 `type=thinking` 帧 `"正在识别你的意图…"`(`event_id = last_event_id + 1`,保证跨 turn resume token 单调)
  - `send_json` 包 `try/except Exception` — WS 已断开场景记 WARNING + 继续分类,不让网络抖动阻塞主路径
  - 调用方 `handle_websocket` 在外层声明模块级 `last_event_id = 0` 跨 turn cursor,`_run_agent_streaming` 返回值续传
- **`nexus/backend/intent/router.py::classify_intent` 超时硬限**:
  - `asyncio.wait_for(8.0)` → `async with asyncio.timeout(5.0):` 上下文管理器(Python 3.11+ 替代 API,对 httpx 挂起 cancel 更可靠)
  - 显式 `except TimeoutError` 分支排在 `except Exception` 之前,日志带超时值
  - 兜底全部返回 `DEFAULT_INTENT`(`"chitchat"`)
  - 模块 docstring 从 "< 8s 超时" 更新为 "5s 硬限超时"

### Added

- **`nexus/backend/api/thinking_parser.py`** — 226 行纯逻辑状态机(无 IO、无 asyncio):
  - 公开 API:`feed(content: str) -> list[tuple[Literal["chunk", "thinking"], str]]` + `flush()`
  - 状态:`"chunk"` ↔ `"thinking"`,转移由 open/close tag 触发
  - hold 缓冲:处理 `<thin` / `</think` 跨 chunk 分片
  - 归一化:`<think>` ↔ `<thinking>` 视为同义,统一归一为 `<thinking>`
  - `flush()` 兜底:未闭合的 thinking 累积按 thinking 帧发,未识别的部分标签按 chunk 发
- **`tests/test_thinking_parser.py`** — 10 单元测试,覆盖正常 / 分片 / 嵌套 / 空标签 / `<think>` 与 `<thinking>` 混用 / stray close / unclosed at flush
- **`tests/test_ws_realtime_streaming.py`** — 3 集成测试(mock LLM 逐 token 验证实时发帧 + thinking 跨分片识别 + final 顺序)
- **`tests/test_intent_heartbeat.py`** — 3 回归测试(慢 LLM 路径发心跳 / `llm=None` 路径发心跳 / `event_id=last_event_id+1` 单调契约)
- **`tests/test_intent_timeout.py`** — 3 超时测试(30s 挂起 LLM 5s 兜底 / 正常路径 task / 源码契约:必须 `asyncio.timeout` 且禁止 `asyncio.wait_for`)
- **`tests/test_use_tauri_ws_placeholder.py::test_ws_emit_chunk_realtime_not_buffered`** — 反向 grep 断言:ws.py 必须 import ThinkingParser + on_chat_model_stream 分支含 `parser.feed` + `send_json` + **禁止** `full_response +=`。回潮立即 CI 红。
- **`frontend/e2e/debug-agnes-message.spec.ts`** — Playwright 8s 首帧断言(实际期望 5s 内),`waitForFunction` 查 `.message-row.is-assistant` 是否有内容或 `.thinking-block`,超时 throw `"Agnes 转圈 bug 复发:8s 内未收到任何内容帧"` + 截图。

### Removed

- **`ws.py` 内的 `import re`** — 已无 `re.findall` 调用
- **`ws.py::_STREAM_CHUNK_SIZE`** — 16 字符切块常量已删
- **`tests/test_ws_resilience.py::test_ws_chunks_response_in_16_char_groups`** 重命名为 `test_ws_chunks_emitted_realtime_no_post_split` — 30 字符响应现在是 1 帧,不再是 2 帧

### Notes

- **`_emit_chat_end.chunks_count` 改为 `len(response_text)` 粗估**:精确计数需要 `_run_agent_streaming` 多返回一个元组元素,留作后续可观测性 PR。本次修复不阻塞。
- **pre-existing 80 行函数上限违规**:`_run_agent_streaming` 现 483 行(原 ~300 + 本次 +180)。本次 fix 不拆函数,留作独立 refactor PR。python_project.md §1.2 要求单函数 ≤ 80 行,差距 6 倍,后续必须处理。
- **`emitted_chunk_text` 与 `last_event_id` 作用域**:两者都是 `handle_websocket` 函数内 module-level 局部变量(非全局),保证 WS 断开后状态自然 GC,跨连接不污染。

### Verified

- `ruff check nexus/` — All checks passed
- `ruff format --check nexus/` — 0 diff
- `pytest tests/ -q` — **527 passed, 12 skipped** in 32s(基线 508 → +19 新测试,零回归)
- 6 次 spec review + 5 次 code quality review,全部通过(含 3 次 fix amend 循环)
- 5 个 task 6 个 commit(每 task 一个,Task 1 多 1 个 refactor amend),Conventional Commits 格式,中文主题 ≤ 50 字符

---

## [Unreleased] — 桌面 APP 架构简化(electron+pyinstaller 双运行时 → pywebview+pyinstaller 单运行时)

### Changed

- **桌面 APP 从 Electron + Python 双运行时,改为 pywebview(WKWebView)+ PyInstaller 单运行时**:
  - 旧:`Electron 主进程 + Renderer + Helper*(GPU/Renderer/Plugin) + nexus-backend(PyInstaller)` 两个独立 runtime 互 spawn
  - 新:`Nexus.app/Contents/MacOS/Nexus`(壳脚本)→ exec `Resources/nexus-backend/nexus-backend`(PyInstaller 单二进制,内嵌 Python 运行时 + pywebview + 后端)
  - **DMG 167MB → 70MB**(arm64,UDZO 压缩),.app 124MB 主要是 PyInstaller _internal
  - **进程数 1**(原来 5+ 个 Electron Helper + Python 子进程)
  - 内存占用大幅降低(无 Chromium,WKWebView 由 macOS 共享)
  - FastAPI 已经在 `/app` 挂载前端 dist,所以 launcher 只需后台线程跑 uvicorn + 主线程 `webview.start()`

### Added

- **`nexus/backend/launcher.py`** — 桌面 APP 入口:`uvicorn.run()` daemon 线程 + `webview.create_window()` 主线程 + `--no-gui` headless 选项
- **`scripts/build_dmg.sh`** — 一键打包(PyInstaller onedir + .app bundle 构造 + hdiutil)
- **`pyproject.toml`** 加 `pywebview>=6.0 ; sys_platform == 'darwin'`(仅 macOS 装,其他平台不依赖)

### Removed

- **`desktop/` 整目录删除** — Electron + TypeScript + electron-builder(~136MB node_modules + 489 行 TS + 180 行测试)
- **`scripts/build_backend_app.sh`** 替换为 `scripts/build_dmg.sh`
- **`frontend/e2e/dmg-cdp/`** 删除(Electron `--remote-debugging-port` CDP attach 测试,新架构不再适用)
- **`pyproject.toml` desktop 引用** 删
- **顶层 `package.json` desktop:* 脚本** 替换为 `build:frontend|build:dmg|build:all`

### Verified

- `ruff check / format`:全过
- `pytest`:468 passed / 12 skipped in 43.92s
- E2E 5/5(真 LLM):简单闲聊 / 长期记忆+身份 / 联网搜索 / 澄清 / 跨 session 隔离
- DMG 本地构建:`scripts/build_dmg.sh` 一次成功,产物 70MB,`/Applications/Nexus.app` 启动后 1 个 `nexus-backend` 进程监听 30000

---

## [Unreleased] — CLI 清理(产品不再提供 CLI,终端用户走 DMG)

### Removed

- **`nexus/cli/` 整包删除** — `install/uninstall/start/stop/restart/status/logs/doctor/setup/config/gateway/ppt` 全部命令失效
  - 历史背景：dev 期 `install()` 写 launchd plist + `shutil.copytree(nexus, ~/.nexus/nexus/)` + 重建 venv,模拟"装机",但产品用户拿到的是 DMG,源码复制路径在用户机器上不存在,plist 启动失败
  - 终端用户路径：**macOS DMG APP**(`/Applications/Nexus.app`,Electron 拉起 PyInstaller onedir 后端)
  - 开发者路径：git clone 后 `python nexus/backend/run.py` + `(cd frontend && npm run dev)`,见 [README.md](./README.md)
- **`nexus/pptmaster/` 整包删除** — `nexus ppt` 命令 + runner 子进程边界,与产品核心(AI Gateway + 长期记忆 + 微信通道)无关
- **`nexus/backend/rubrics/_cli_helpers.py` 删** — 仅被已删 CLI 引用
- **`nexus/backend/rubrics/exporter.register_export_command()` 删** — CLI 注册逻辑,函数无调用方
- **`tests/test_cli_commands.py` / `test_config_loading.py` / `test_pptmaster.py` / `test_rubric_exporter.py::test_register_export_command_is_callable` 删** — 对应失效 CLI 的测试
- **`pyproject.toml` `[project.scripts]` 删** — `nexus` console script 入口

### Changed

- **README.md** 重写顶部"快速开始":终端用户走 DMG,开发者走 git clone,删失效 CLI/一键安装/pip install 段
- **CLAUDE.md** 命令列表删 CLI,加 2026-06 清理说明
- **SPEC.md** `## CLI` 段改写为开发者 git clone 步骤
- **`.claude/settings.local.json`** 删 `nexus gateway status` 权限白名单

### Verified

- ruff check 0 error, format 109 files 0 diff
- pytest **443 passed / 12 skipped**(原 456,减 13 个失效 CLI 测试)
- E2E 5/5 通过:简单闲聊 / 长期记忆+身份 / 联网搜索 / 澄清 / 跨 session 隔离(脚本在 `/tmp/e2e_dmg_user.py`,模拟 DMG APP WS 帧)

---

## [Unreleased] — 记忆子系统重构(对齐 deepagents 框架)

### Changed

- **记忆机制**: 完全对齐 deepagents 0.6.8 原生框架,删除自定义 `MemoryService` / `EvolutionService` 整层(548 行死代码 + 4 个旧 `@langchain_tool`)
  - 长期记忆由 deepagents `MemoryMiddleware` 自动加载 `~/.nexus/AGENTS.md`(用户级)+ `nexus/.deepagents/AGENTS.md`(项目级),以 `<agent_memory>...</agent_memory>` 段注入 system prompt
  - LLM 通过内置 `edit_file` / `write_file` 自更新 AGENTS.md;`QualityGateMiddleware` 在 `wrap_tool_call` 阶段拦截写入并跑 `MemoryFilter` 忠实度评估,拒绝幻觉/低价值记忆写入
  - 持久化层: `langgraph.store.memory.InMemoryStore`(重启丢 session 临时数据)+ AGENTS.md(跨重启持久化)
- **`nexus/SOUL.md`** 迁至 `nexus/.deepagents/AGENTS.md`(身份/规则保留)
- **`nexus.db` schema**:
  - `memory` → `memory_legacy`(改名,数据保留可查,只读)
  - `tool_stats` / `session_stats` 表删除(深 agents 框架不需要)
- **新增脚本**:
  - `scripts/migrate_legacy_memory.py` — 一次性迁移旧 `memory` 表 explicit 偏好 → `~/.nexus/AGENTS.md` `## Migrated Preferences` 段,幂等,支持 `--dry-run`
  - `scripts/seed_user_agents_md.py` — 首次启动初始化 `~/.nexus/AGENTS.md` 空模板,幂等
- **Bug 修复**: `FilesystemBackend(virtual_mode=True)` 拒绝绝对路径,导致 `~/.nexus/AGENTS.md` 被 `MemoryMiddleware` 静默跳过 → LLM 失去身份感;改 `virtual_mode=False`,由 `FilesystemPermission` + `QualityGateMiddleware` 在更上层兜底安全
- **测试**: 390 passed(9 个新增 `test_migrate_legacy_memory.py`)

### Migration Guide

升级到本版本后,执行一次:

```bash
# 1. 备份 db(脚本内部也会跳过已迁移的 db,但先备份更稳)
cp ~/.nexus/nexus.db ~/.nexus/nexus.db.bak.$(date +%s)

# 2. 跑迁移(explicit → ~/.nexus/AGENTS.md,改 memory 表名 → memory_legacy)
python scripts/migrate_legacy_memory.py

# 3. 验证
sqlite3 ~/.nexus/nexus.db ".tables"  # 应见 memory_legacy, 不见 memory
cat ~/.nexus/AGENTS.md               # 应见 ## Migrated Preferences 段含你的旧偏好
```

无 explicit 偏好 → 脚本无 op,安全跳过。

---

## [Unreleased] — 上下文窗口配置化(NEXUS_CONTEXT_WINDOW 默认 200K)

### Changed

- **`NEXUS_CONTEXT_WINDOW` 默认从 `32000` 改为 `200000`**:
  - WHY:旧值 32K 是 Nexus 项目早期假设,与当前 MiniMax-M3 实际规格不符;Claude 200K、GPT-4 Turbo 128K 等主流模型都在 100K+ 区间,默认 200K 更贴近实际部署场景。
  - **Breaking**:已部署且未设 `NEXUS_CONTEXT_WINDOW` 的用户,升级后 UI 上下文占比 + 自动压缩触发阈值都会按 200K 重算。如需回滚旧值:`export NEXUS_CONTEXT_WINDOW=32000`。
- **`nexus/backend/api/ws.py::_estimate_tokens` 默认 `context_window` 从 32000 改为 200000**,与 `NEXUS_CONTEXT_WINDOW` 同步;0/负数兜底值也跟着改。
- **`nexus/backend/agent.py` 注释更新**:解释 deepagents `compute_summarization_defaults` 通过 `model.profile["max_input_tokens"]` 算 trigger = `max × 0.85`,默认 200K → 170K 触发阈值。

### Added

- **`ResilientRunnable._resolve_model_profile()`**(`nexus/backend/llm/wrapper.py`):
  - 把 `NEXUS_CONTEXT_WINDOW` 暴露为 `model.profile["max_input_tokens"]`,驱动 deepagents 自动按 0.85 fraction 计算压缩 trigger。
  - 切换不同上下文窗口的模型(200K / 1M / 32K)只需改 env,代码不动。
- **`tests/test_llm_profile.py`** 新增:覆盖正常路径(默认 200K / env 覆盖 128K)、边界条件(32K / 2M)、异常路径(env="abc" 抛 ValueError)、契约验证(200K × 0.85 = 170K trigger)。

### Migration Guide

```bash
# 不需操作:默认 200K 已生效
# 如要回滚旧值:
export NEXUS_CONTEXT_WINDOW=32000
# 切换其他模型(如 1M 上下文的 Gemini 1.5 Pro):
export NEXUS_CONTEXT_WINDOW=2000000
```

### Tests

- `tests/test_llm_profile.py`:8 个新 case 覆盖 profile 契约
- `tests/test_estimate_tokens.py`:default / 0 兜底 / max clamp 测试同步更新到 200K

---

## [Unreleased] — deepagents 依赖升级(0.6.8 → 0.6.12)

### Changed

- **`deepagents` 从 `0.6.8` 升级到 `0.6.12`**,连带 `langchain-core` `>=1.4.0` → `>=1.4.8` / `langchain` `>=1.3.4` → `>=1.3.11` / `langchain-anthropic` `>=1.4.3` → `>=1.4.7`:
  - **驱动原因**:研究 4 个 patch 版本(0.6.9 → 0.6.12)源码 + release notes,确认 4 个核心 API(`compute_summarization_defaults` / `create_summarization_middleware` / `_DeepAgentsSummarizationMiddleware.wrap_model_call` / `_should_summarize`)跨 5 版本签名零变化,Codex 删除显式 SummarizationMiddleware 的 dedup 推理(`serialized_name="SummarizationMiddleware"`)继续成立。
  - **行为兼容**:`ResilientRunnable._resolve_model_profile()` → `model.profile["max_input_tokens"]` → deepagents 0.85 fraction 的链不变。

### Added(自动获得,零代码改动)

- **0.6.9 性能优化**:`summarization middleware` 改成 "Count tokens once per model call"(PR #3877),引入 `_token_counter_accepts_tools()` helper 探测 `tools=` 参数签名,工具 schema 现在参与 token 计数。ResilientRunnable 没传 custom counter,走默认 → 自动生效。
- **0.6.9 性能**:`filesystem system prompts` + `grep/glob matchers` 加缓存(PR #3889 / #3887 / #3886)。与我们 agent 行为无关,但会降低 cold-start 工具调用延迟。
- **0.6.9 子能力**:`subagent response format` 可配置(PR #3882)。我们暂未用,留作未来扩展点。

### Notes

- **0.6.12 新增 `deepagents[aws]` extra**(Bedrock 自动 prompt caching,PR #4108)与 **media references 保留**(PR #3990)对我们**零影响**:不用 Bedrock、不处理 image / file URL。如未来切 Bedrock,`pip install deepagents[aws]` 即可启用。
- **0.6.10 / 0.6.11 各自一个 bug fix**:`model_matches_spec` 比较 provider 字段(#3943)、`BaseSandbox async` helpers 走 `aexecute`(#3996)。我们未触这两条路径,无回归风险。

### Verified

- `pip install --upgrade deepagents==0.6.12`:成功,连带 langchain 全家桶升到 1.3.11+
- `pytest tests/test_llm_profile.py test_estimate_tokens.py test_agent_memory.py test_checkpointer_sqlite.py test_deepagents_integration.py test_resume_token.py test_observability_logger.py test_run_coro_sync.py`:**88 passed in 3.79s**
- `pytest tests/`: **497 passed, 8 failed**(8 个失败全在 `test_e2e_features.py`,需 backend 运行 + 真实 LLM API key,pre-existing 基础设施依赖,跟升级无关)
- `ruff check nexus/`:5 个 pre-existing 错(launcher.py 的 Objective-C 桥接 N802/N806 + runtime_main.py 一个 trailing newline),**未引入新 lint**

---

## [Unreleased] — 修复 UI 上下文占比误报

### Problem

用户实际场景:UI 显示"上下文 █████████░ 89% (178k/200k)",但
deepagents 自动压缩没触发(实际 trigger 阈值是 200K × 0.85 = 170K)。
根因:`_estimate_tokens` 用的字符系数(中 ×2.5 / 英 ×0.25 / 其他 ×0.5)
跟 deepagents 内部 `count_tokens_approximately` 差 ~10×。同时该函数
只统计"本轮响应",不算整个对话上下文。

实测对照(71200 中文字符):
  | 估算方式 | tokens | 占比 |
  |---|---|---|
  | 旧字符系数 | 178,000 | 89%(误导) |
  | langchain `count_tokens_approximately` | ~17,950 | 9%(真实) |

### Changed

- **`nexus/backend/api/ws.py::_estimate_tokens` 改用
  `:func:langchain_core.messages.utils.count_tokens_approximately`**:
  - 函数签名从 `(text: str, context_window: int)` 改为
    `(content: str | list, context_window: int)` — 接受字符串(测试/降级用)
    或 messages 列表(生产用整个会话上下文)
  - 底层委托给 langchain 启发式,跟 deepagents `SummarizationMiddleware.
    _should_summarize` 用**同一套** token 估算
  - 空内容短路:空 str / 空 list 直接返回 `(0, 0.0)`,避免空消息被算成
    ~4 tokens(per-message overhead)
- **WS caller 范围扩展**:`_run_agent_streaming` 里调
  `_estimate_tokens(prompt["messages"] + [新 assistant 响应], ...)`,
  传**整个对话上下文**而不是只传本轮响应。这样 UI 显示的 % 才是
  "会话占比",不是"响应占比"。

### Tests

- `tests/test_estimate_tokens.py` 全面重写:
  - 去掉依赖字符系数的固定值断言(旧测试 4字中文 = 10 tokens 之类)
  - 加 str / list 两种输入的覆盖
  - 加核心回归保护:`test_long_chinese_conversation_realistic_usage`
    验证 50 轮 × 240 中文字符的真实长对话估出 < 5%(旧系数会算成 ~30%)
  - 加 `test_calls_count_tokens_approximately` 用 mock 锁定底层实现,
    防止有人改回字符系数

### Verified

- `pytest tests/test_estimate_tokens.py`:**13/13 通过**
- `pytest test_estimate_tokens + test_llm_profile + test_agent_memory +
  test_resume_token + test_ws_resilience`:**65/65 通过,无回归**

---

## [v0.1.0] — 2026-06-21 — 首次内测交付

**核心**: 把 Nexus 从「能跑」推进到「能装能用」。AI Gateway 全栈接通(后端 + 前端 + **桌面端 DMG 安装包**)、质量门上线、可观测性落地、意图识别路由、CI/CD 双线。
**详情**: 见 `docs/RELEASE_NOTES_v0.1.0.md`
**测试**: 378 backend tests pass + Playwright DMG CDP 真环境 E2E
**产物**: `release/Nexus-1.0.0-arm64.dmg`(175 MB,macOS arm64,未签名)

本节合并自以下 3 段历史 Unreleased 内容:

---

## [Unreleased] — 意图识别路由

**分支**：`codex/macos-dmg-app`（6 commits since `362809b`，356 tests，DMG CDP 真实环境 E2E 验证通过）

> 给 Nexus 单 LLM 主对话加 1-shot 意图识别层：每条 user 消息先经 1 次轻量工具调用分类，分类结果落库 `messages.intent`，与现有质量门联动（chitchat 走原短路、knowledge/task 走完整 judge）。
> 详细计划见 `docs/superpowers/plans/2026-06-19-intent-recognition-routing.md`。

### Added
- **`nexus/backend/intent/router.py`**：`classify_intent()` 用 LangChain `bind_tools` 1-shot 分类 `chitchat` / `knowledge` / `task`，8s 超时 + 4 条兜底路径（异常 / 超时 / 无 tool_call / 未知 tool 名）一律返回 `chitchat`（最安全：质量门已有 chitchat 短路）
- **`nexus/backend/intent/__init__.py`**：统一导出 6 个公共符号
- **DB 迁移**：`messages` 表新增 `intent TEXT` 列，走 `_ensure_column()` 自动 ALTER，老库无感
- **WS 集成**：`handle_websocket` 收到 user 消息时先调 `_classify_and_record` 分类并把 intent 一并写库；通过 `get_intent_llm` 回调注入 LLM 实例
- **零新依赖**：复用主 `ChatModel` 实例（与 quality gate 的 `judge_llm` 共用同一对象），不增加 token 配额与网络连接

### Tests
- `tests/test_intent_router.py`：6 用例（3 类命中 / 无 tool_call / LLM 异常 / 超时 / 未知 tool 名）
- `tests/test_intent_ws_integration.py`：2 用例（`_classify_and_record` 路径、`get_intent_llm=None` 兼容）
- `tests/test_db_migrations_intent.py`：3 用例（fresh create、列存在、迁移幂等）
- `frontend/e2e/dmg-cdp/test-dmg-intent.mjs`：DMG CDP 真实环境 2 用例（闲聊 → chitchat 137 字响应；求和算法 → knowledge 431 字响应），覆盖 WebSocket 流式 + sqlite3 直查 intent 列

### Risk Mitigation
- 退化构造失败时所有输入判为 chitchat，质量门仍按原路径运行；INFO 日志提示运维
- `_classify_and_record` 完全运行在事件循环内（`async def`），无子线程桥接风险
- `models.json` 写入、API key 日志、密钥输出等原有约束未破坏

---

## [Unreleased] — 可观测性子系统（JSONL + 4 产品事件）

**分支**：`codex/macos-dmg-app`（13 commits since `6448722`，378 tests，真实环境 E2E 验证通过）

> 给 Nexus 加 observability 子系统：JSONL 结构化日志 + 4 个产品事件 + LangChain callback 通道复用 + env 三档配置。不造轮子，复用 stdlib `logging.handlers.RotatingFileHandler` + LangChain `BaseCallbackHandler`。
> 详细计划见 `docs/superpowers/plans/2026-06-20-observability-subsystem.md`，运维文档见 `docs/operations/logging.md`。

### Added
- **`nexus/backend/observability/events.py`**：4 个产品事件 dataclass（`ChatStart` / `IntentClassified` / `QualityVerdict` / `ChatEnd`），frozen + `to_dict()` 序列化，`EVENT_SCHEMA_VERSION="1.0.0"`
- **`nexus/backend/observability/sink.py`**：`EventSink` 类，JSONL / text 双格式，10MB × 5 `RotatingFileHandler` 轮转，threading.Lock 并发安全，lazy 父目录创建
- **`nexus/backend/observability/logger.py`**：`setup_logging()` 幂等入口，env 三档（`NEXUS_LOG_FORMAT` / `NEXUS_LOG_FILE` / `NEXUS_LOG_LEVEL`），stdlib `_JsonFormatter`（无第三方依赖），预设 `deepagents=INFO` / `langchain=WARNING` / `langchain_core=WARNING`
- **`nexus/backend/observability/handler.py`**：`NexusLogHandler(BaseCallbackHandler)` 6 回调：on_llm_start/end（含 token 统计）/ on_tool_start/end / on_chain_start/end，duration_ms 用 `time.monotonic` 算，sink 写失败吞异常
- **集成点**：
  - `nexus/backend/main.py` 启动期调 `setup_logging()` 取代 `logging.basicConfig`
  - `nexus/backend/agent.py` 总是挂 `NexusLogHandler`（走 EventSink 落盘），仅 `NEXUS_AGENT_VERBOSE=1` 时额外挂 `StdOutCallbackHandler`
  - `nexus/backend/api/ws.py` 新增 `emit_chat_event()` 公开 API + 4 个 anchor 点（chat.start / intent.classified / quality.verdict / chat.end）
  - `chat_start_monotonic` 在 ChatStart 之后立即 `time.monotonic()`，ChatEnd 复用算 `duration_ms`

### Tests
- `tests/test_observability_events.py`：5 用例（round-trip / latency_ms / scores dict / duration+retries / frozen）
- `tests/test_observability_sink.py`：5 用例（JSONL 追加 / text 格式 / 父目录创建 / 4 线程 × 50 并发 / close 幂等）
- `tests/test_observability_logger.py`：5 用例（autouse fixture 隔离 root logger，验证 default path / text 格式 / json 格式 / level env / 幂等）
- `tests/test_observability_handler.py`：4 用例（isinstance BaseCallbackHandler / on_llm_end 写 2 事件 / on_tool_start 含 tool 名 / sink 失败不破 callback）
- `tests/test_observability_ws_integration.py`：3 用例（emit_chat_event 写 sink / 吞异常 / 4 event round-trip）

### Verification
- 真实环境 E2E（`NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/tmp/e2e-final.log`）：2 次 chat（chitchat + 知识类）触发 4 条 `chat.*` 事件（chat.start + chat.end 各 2），verdict 均为 accept，LLM 调用 2 次，intent 分类正确（chitchat / knowledge 各 1）
- 端到端验证脚本：`/tmp/ws-verbose-test.py` / `/tmp/ws-knowledge-test.py` / `jq` 查询示例见 `docs/operations/logging.md`
- pytest：378 passed（原 356 + 新 22）

### Limitations
- `chunks` 字段当前是 `len(response_text) // 16` 估算值（精确 chunk count 在 `_run_agent_streaming` 内部），后续若需精确值扩展该函数返回 `chunk_count` 即可
- `chat.end` 当前只在正常完成分支 emit；澄清挂起 / 错误流分支不发，后续若需覆盖补发可扩展 `handle_websocket`
- `langchain` / `langchain_core` 默认 WARNING 级，避免 stream / token 刷屏；`deepagents=INFO` 是因为它本身日志覆盖少
- ruff 仍有 9 条 pre-existing 错（`tests/test_config_loading.py` / `tests/test_fixes_round2.py` / `tests/test_wechat_smoke.py` 的未排序 import / 未用导入），与本任务无关，未在本任务中修复

### Files
- 新增：`nexus/backend/observability/{events,sink,logger,handler,__init__}.py`（5 文件）
- 新增：`tests/test_observability_{events,sink,logger,handler,ws_integration}.py`（5 文件）
- 新增：`docs/operations/logging.md`
- 修改：`nexus/backend/main.py` / `nexus/backend/agent.py` / `nexus/backend/api/ws.py`（3 文件）
- 顺手：`tests/test_observability_handler.py` 顶部 `import dataclasses` 整理（style）；`handler.py` docstring 与实现对齐

---

## [Unreleased] — Phase 1+2 容错 + 质量门

**合并提交**：`7ea9cbe`（22 commits, 303 tests, 真环境验收通过）

> 本次发布包含两个大阶段：Phase 1（容错）与 Phase 2（质量门）。
> 详细计划见 `docs/superpowers/plans/`，进度见 `docs/superpowers/progress.md`。

### Added — Phase 1：容错

#### 断线续传（WebSocket 重连）
- 新增 `nexus/backend/resume.py`：HMAC-SHA256 + base64url 签名的 resume token
- 新增 `GET /api/sessions/{session_id}/resume` 端点：客户端用上次收到的最后一个 `event_id` + 收到的 token 续拉事件
- 新增 `resume_tokens` 表（`token`, `session_id`, `last_event_id`, `expires_at`）
- WS 断线后重连 → 服务端从 Redis/SQLite 重放未确认事件，不丢消息
- 端到端测试：`tests/test_resume.py`（含 token 过期、签名验证、event_id 单调性）

#### LLM 错误分类与降级
- 新增 `nexus/backend/llm/errors.py`：`ClassifiedError` + `LLMErrorKind` 枚举
  - 错误分类：`AUTH` / `RATE_LIMIT` / `TIMEOUT` / `NETWORK` / `BAD_REQUEST` / `SERVER` / `UNKNOWN`
  - 每类标记 `retryable` 标志，驱动重试策略
- 新增 `nexus/backend/llm/wrapper.py`：`ResilientRunnable`（Pydantic v2 `BaseChatModel` 子类）
  - 内置指数退避重试（最多 N 次）
  - 失败时打点日志 + 抛 `ClassifiedError` 给上层降级
  - 已被 `nexus/backend/agent.py` 的 `get_llm()` 工厂使用

#### WS 边界
- WS 处理器在 judge / 主 LLM 失败时返回结构化 `error` 事件而非断开连接
- 客户端可重连后用 resume token 续传
- 测试：`tests/test_ws_fault_tolerance.py`

#### 配套 CLI
- `scripts/check_lm.py`：诊断 LLM 凭据、连通性、当前激活模型

### Added — Phase 2：质量门（Rubrics）

#### Rubric 数据层
- 新增 `nexus/backend/rubrics/schemas.py`：
  - `RubricVerdict` 枚举（`ACCEPT` / `REPAIR` / `REJECT`）
  - `Rubric` / `Score` / `RubricVerdictResult` 三个 frozen dataclass
  - 4 个内置维度常量 + `DEFAULT_RUBRICS` 元组
  - 阈值映射规则：`>=0.8` → ACCEPT，`>=0.6` → REPAIR，否则 REJECT
  - `safety` 单独更严：`>=0.9` / `>=0.7`
- 全部不可变（`frozen=True`），符合 CLAUDE.md §11

#### Rubric Judge
- 新增 `nexus/backend/rubrics/judge.py`：`RubricJudge`
  - 并发 4 维度评分（`asyncio.gather`）
  - 单 rubric 超时 30s（`per_rubric_timeout`）
  - JSON 解析失败时重试 1 次（`max_parse_retries=1`）
  - 全失败抛 `RubricJudgeError`，由 pipeline 降级 REJECT
- 新增 `nexus/backend/rubrics/prompts.py`：4 个中文 prompt 模板（200-500 字，含正反例 + 严格 JSON 输出约束）
- 新增 `nexus/backend/rubrics/tool_evaluator.py`：tool_correctness 维度的工具调用正确性评估

#### Repair 决策
- 新增 `nexus/backend/rubrics/repair.py`：`RepairStrategy`
  - `safety_veto=True`（plan 强制）：safety < 0.5 → 一票否决，直接 REJECT
  - `max_repair_attempts=1`（plan 强制）：首次 REPAIR 触发主 LLM 重生，二次仍 REPAIR → REJECT
  - 加权聚合：`Σ(score_i × weight_i)`
- 新增 `nexus/backend/quality/pipeline.py`：`QualityPipeline`
  - 公开方法 `run_with_quality(question, raw_response, message_id=None) -> FinalResponse`
  - 三段式：judge → decide → repair → persist
  - 异常全收口：judge 失败、主 LLM 失败 → 降级 REJECT fallback，不抛
- 新增 `nexus/backend/quality/__init__.py`

#### DPO / KTO 偏好数据导出
- 新增 `nexus/backend/rubrics/exporter.py`：`PreferenceExporter`
  - `export_dpo(records, out_path)`：gap ≥ 0.3 的成对偏好
  - `export_kto(records, out_path)`：逐条二元偏好
- 新增 `nexus/backend/rubrics/_cli_helpers.py`：`load_preference_records`
  - **修复**：从 quality_scores 按 `message_id` 分组 + 求平均，避免同 message 排序错乱
- 真环境 100 轮对话可导 30+ 条 DPO

#### Meta-eval
- 新增 `nexus/backend/rubrics/meta_eval.py`
  - `compute_pearson(xs, ys)`：纯函数，常数方差返回 0
  - `compute_cohens_kappa(a, b)`：纯函数，单类别返回 0
  - `KAPPA_ALERT_THRESHOLD = 0.4`（plan 强制报警线）
  - `MetaEvalSample` / `MetaEvalResult`（frozen）
  - `run_meta_eval(judge, samples)`：集成 + 算指标
- 新增 `scripts/eval_rubrics.py` CLI
  - 退出码：0 = kappa ≥ 0.4，1 = kappa < 0.4
  - CI 集成入口

#### 配套数据
- 新增 `data/rubric_eval_samples.jsonl`：12 条人工标注样本（覆盖 4 维度 × accept/repair/reject）
- 新增 `data/eval_report.json`：当前 meta-eval 结果（Pearson 0.973, kappa 0.591）

### Changed — 集成

- `nexus/backend/main.py`：
  - 启动期构造 `QualityPipeline(judge=RubricJudge(llm=...), repair_strategy=..., main_llm=...)`
  - 注入 `app.state.quality_pipeline`
  - **关键修复**：judge LLM 改用 `get_llm()` + `get_active_model()`，与主 Agent 一致（之前用 `_agent` 报错因 deepagent compiled graph 不是 chat model）
- `nexus/backend/api/ws.py`：
  - 在调 pipeline 前生成 `message_id = str(uuid.uuid4())`
  - 把 `message_id` 同时透传给 `run_with_quality` 和 `add_message`，保证 quality_scores 行可关联到具体 assistant 消息
- `nexus/backend/quality/pipeline.py`：
  - `run_with_quality` 新增 `message_id` 参数（默认 `None`）
  - `_persist_scores` 把 `message_id` 透传给 `save_quality_score`

### Fixed — 真环境验证发现的 3 个 bug

1. **`RubricJudge(llm=_agent)` 误用**
   - 现象：judge 报 `AttributeError: 'CompiledGraph' object has no attribute 'ainvoke'`（实际能调，但返回的是 LangGraph state dict）
   - 修复：改用 `get_llm()` 构造的 `ResilientRunnable`（真正的 `BaseChatModel` 子类）

2. **judge LLM 404**
   - 现象：judge 调 LLM 返回 `404 not_found`
   - 根因：`CONFIG["model_name"]` / `CONFIG["minimax_api_base"]` 默认值与主 Agent 的 `get_active_model()` 不一致
   - 修复：`main.py` 和 `scripts/eval_rubrics.py` 都改用 `get_active_model()` 取值

3. **`quality_scores.message_id` 全部为 NULL**
   - 现象：所有 quality_scores 行的 `message_id` 字段都是 NULL
   - 根因：pipeline 没接收 message_id
   - 修复：见 Changed 节

### Tests

- **测试总数**：303 passed（合并时）
- **新增 / 修改**：
  - `tests/test_rubric_schemas.py`
  - `tests/test_rubric_judge.py`
  - `tests/test_rubric_repair.py`
  - `tests/test_rubric_meta_eval.py`
  - `tests/test_quality_pipeline.py`（含 message_id 透传 2 个测试）
  - `tests/test_resume.py`
  - `tests/test_ws_fault_tolerance.py`
  - `tests/test_llm_wrapper.py`
  - 配套集成测试若干

### Documentation

- 新增 `docs/operations/quality.md`：质量门调优指南（阈值、prompt、meta-eval、故障排查）
- `docs/superpowers/progress.md`：更新 Phase 1+2 全部完成 + 真环境验收 4 条全过

### Verified — 真环境验收

`.venv/bin/python scripts/verify_phase2.py --all` 全过：

| 步骤 | 验证内容 | 结果 |
|------|---------|------|
| 1 | WS 烟测（发 "你好" 收到 done） | ✅ |
| 2 | 诱导幻觉 → REJECT（3 个不存在的概念） | ✅（8 条 REJECT 记录入库） |
| 3 | REPAIR 路径触发 | ✅（verdict 分布里有 repair） |
| 4 | 100 轮对话 + 导出 ≥ 30 DPO | ✅（导出 34 DPO / 68 KTO） |
| 5 | meta-eval Pearson + kappa | ✅（Pearson 0.973 / kappa 0.591 ≥ 0.4） |

---

## 版本策略

Nexus 仍在 pre-1.0 阶段，版本号在 0.x 区间。本节内容合并到下次正式发版时再切分版本号。

后续每次 phase 合并后追加新节，标题格式：

```
## [Unreleased] — <阶段名> + <一句话总结>
```

---

## [Unreleased] — 下一阶段占位

### Changed — 依赖清理(2026-06-21)

- **卸 `ppt-master` 依赖**:
  - 原 `pyproject.toml` 用 `ppt-master @ git+https://github.com/hugohe3/ppt-master.git`,该仓库 main 分支不再包含 Python 包配置,导致 CI `pip install -e ".[dev]"` 阶段失败(`does not appear to be a Python project`)
  - 改成不通过 pip 装,文档说明按需安装(`pip install ppt-master`,需 Python 3.12+)
  - runner.py 子进程调用代码完全不动,真要用 PPT 生成的用户单独装就行
  - 提交:`58a1b4d fix(deps): 卸 ppt-master 依赖`

---

## [Unreleased] — 下一阶段占位

下一阶段(预计 v0.2.0)重点：

- macOS 代码签名(接入 Apple Developer ID,DMG 自动签名)
- `chunks` 字段精确化(扩展 `_run_agent_streaming` 返回 `chunk_count`)
- `chat.end` 在澄清挂起 / 错误流分支补发
- 澄清交互(ask_user 工具)端到端接入前端 UI
- 偏好数据导出(DPO/KTO)接入训练流程(暂不训练,只导出)

---

## 链接

- [v0.1.0 release notes](./RELEASE_NOTES_v0.1.0.md)
- [可观测性计划归档](./superpowers/plans/2026-06-20-observability-subsystem.md)
- [意图识别路由计划归档](./superpowers/plans/2026-06-19-intent-recognition-routing.md)
- [质量门调优指南](./operations/quality.md)
- [日志查询指南](./operations/logging.md)
