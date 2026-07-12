# 2026-07-12 全栈代码审查报告

## 范围与方法

- **范围**:广度优先全栈扫。后端 `nexus/backend/`(76 文件,15220 行)+ 前端 `frontend/src/`(components/hooks/store/lib/types)+ 桌面桥接 `desktop/` 子目录。
- **维度**:4 个 —— 代码质量 / 架构与可维护性 / 性能与并发 / 安全与可靠性。
- **执行策略**:A+B 混合。本会话串行扫描后端核心 9 个文件(主流程 + WS + 中间件 + DB + LLM 包装),并由 3 个 Explore 子代理并行扫前端。
- **基线约束**:`ruff check .` 已 0 错误(本会话确认),`python_project.md` §1.2(单文件 ≤ 800 / 单函数 ≤ 80)在严格意义上的存量违规项见下表。
- **未深度看**:`tests/`(已通过,假设约束同等)、`nexus/cli/` 已删、`frontend/build/` 等构建产物。

## 文件规模(后端 ≥ 200 行的 32 个)

| 行数 | 文件 | 接近红线? |
| --- | --- | --- |
| 785 | `api/ws/streaming.py` | 是(800) — 已拆出 `streaming_hitl.py` |
| 562 | `main.py` | 否 |
| 503 | `db.py` | 否 |
| 501 | `api/ws/handlers.py` | 否 |
| 487 | `llm/wrapper.py` | 否 |

余皆 < 400 行,整体 §1.2 满足。**仅 `streaming.py` 离 800 红线最近**(15 行额度)。这条线上有持续投入(`60f6686` 拆 `streaming_hitl`),但继续向红线推进风险高。

## 核心架构观察(动手前必读)

1. **WS 协议层已经过 3 轮重构**,形成 `streaming.py / streaming_hitl.py / finalize.py / handlers.py / registry.py / observability.py` 的清晰分层。`_finalize_after_stream` 是 `ca6dec5` 之后的关键解耦,把"普通 user 消息路径"和"confirmation_response 续流路径"合并消除路径分叉。架构高度直觉。
2. **HITL 三层防御**(per-call 弹窗 + QualityGate 守 AGENTS.md + 危险路径 deny)架构整齐,`PathAwareHITLMiddleware` 的 `_DANGEROUS_PREFIXES` 把 macOS symlink 漂移(`/tmp` → `/private/tmp`)考虑周到。
3. **Channel 重构已完成**(C4/Gateway 接管路由),`gateway.py` 集中处理 IM 入站,但 `_call_agent` 与基类职责混在 200 行里 —— 微小架构债。
4. **memory_legacy 表已是孤儿 schema**:v0.2+ 长期记忆迁至 AGENTS.md 文件后,该表 5 个索引从无 read(仅 db.py 内部引用)。保留只为回查,但每开新库会白白占空间。
5. **LLM 韧性链完整**:ResilientRunnable + StreamGuard + GraphInterrupt 透传 + reason model profile,Phase 1 4 件套(超时 / 重试 / 降级 / 续流)实现干净。

## 维度 1:代码质量(Quality)

### High

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| Q-H1 | `ChatArea.tsx`(800+,整文件) | 单文件 813 行,内含 ChatArea 主组件 + ClarificationForm + 错误码常量 + 消息状态机。11 个独立 `useStore` 订阅。`handleWsMessage` 172 行 switch 内嵌 `ensureAssistantPlaceholder` 闭包。`handleSend` 与 `handleClarificationSubmit` 重复约 20 行 "ws 守卫 + 双 push + send" 模板。 |
| Q-H2 | `db.py:357-381` `list_sessions` | Python 层 wechat 过滤 + 标题解析 → 标题用空格切取 `account_id`,这格式如果在 history 改容易坏。**严重**:title 里取 acc_id 是脆弱的字符串解析,数据迁移后无法回放。改成会话表加 `account_id` 列。 |
| Q-H3 | `db.py:322-347` `find_latest_session_by_user` | `LIKE '%user_id%'` 即使有 escape 也仍是全表扫描(messages 没有索引覆盖 content)。1000+ session 时会拖慢 wechat 重启。考虑 `sessions.channel_meta JSON` 列存 user_id,加索引。 |
| Q-H4 | `wechat_channel.py:202-277` `_poll_messages` | 单函数 76 行,内嵌三层 try/except + asyncio 调度逻辑。`_handle_incoming_message` 与上下文耦合,未分离"读消息"与"处理消息"。**可读性差**:含嵌套 try/except,改一处易破坏其它路径。 |
| Q-H5 | `gateway.py:96-198` `route_message` | 单函数 100+ 行,8-10 个 await 步骤分支,职责 7 个(会话/持久化/agent/广播/发送/错误/锁)。命中 §1.5 "单一职责"违例。 |

### Medium

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| Q-M1 | `ModelConfigModal.tsx:19/47/83` | 表单初始值在 3 处复制粘贴(`api_base` 默认 `'https://api.minimaxi.com/v1'` 硬编码)。4 处 `catch { console.error }` 吞异常。 |
| Q-M2 | `WechatPluginModal.tsx:36,89` | `pollTimerRef` 的清理逻辑在 2 处复制。 |
| Q-M3 | `setup/useBootstrap.ts:33/41` | `activeModelName` 返回但 `DesktopShell` 从未解构 —— 死代码。 |
| Q-M4 | `useWebSocket.ts:76` | `JSON.parse` 失败时把原始字符串当 `T` 强转透传,业务方必然崩。 |
| Q-M5 | `useTauriWs.ts:63` | `ws_open` 失败后注入伪 `error` 帧(`error_code: ws_open_failed`),混淆协议语义。 |
| Q-M6 | `f-string 日志到处`:如 `main.py:391`、`gateway.py:114/124/138/146/148` 等 30+ 处用了 f-string 而不是 `%s` lazy formatting。Python `logging` 在 level 过滤后的开销被白白花了,**且**与 python_project §1.6 风格不一致("用 logging 不要 print")。 |
| Q-M7 | `wechat_login.py:43,48,67` | `_get_remaining_pause_ms` 等方法调用 `asyncio.get_event_loop().time()` 在新 loop 上下文里已被 Python 3.12 deprecation warning。 |
| Q-M8 | `fact_check.py:282-298` `_extract_content` | 用 `getattr(response, "content", "") or ""` fallback 容易吞掉有效空字符串(LLM 空响应也走"有效"路径),失败排查难。 |

### Low

- `fact_check/_verify_result` 的 dataclass recursion 没收敛限制,极端嵌套会 stack overflow(超 1000 层),可信度低。
- `ToastHost.tsx:44` div 而非 button,无键盘关闭。
- `Sidebar.tsx:39` 排序在顶层,每次 render 重建 Date 对象数组。

## 维度 2:架构与可维护性(Architecture)

### High

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| A-H1 | `main.py:28-36` 模块级全局 | `_agent / _mcp_tools / _agent_lock / _agent_ready_event / _main_loop / _agent_init_started / _app_ref` 7 个全局可变状态。python_project §1.9 "全局可变状态(常量除外)"违例。**By design?**:留了模块级 lazy 模式(避免 import 时构造 agent),但拆 `class AppState` / `class AgentState` 放进 `lifespan.app.state` 是更"FastAPI 风格"的写法。 |
| A-H2 | 前后端 WS 鉴权:**双方契约错位** | 后端 `main.py:402` 强制读 `?token=` query param(已 hmac.compare_digest,合理);前端 `lib/api.ts` 把 `DEFAULT_TOKEN = 'nexus-default-token'` 硬编码(子代理 SEVERE finding)。**两边都没用 subprotocol**,且把 token 走 URL(子代理 SEVERE finding)。 |
| A-H3 | `useStore.ts`(frontend, 139 行) | 全局 Zustand store 把 11 个 setter + persist config 混在一起:持久化偏好(darkMode)与瞬态业务流(wsConnected/conversationMessages/pendingConfirmation/channels inbox)单 store,违反 "slice per concern" 模式。 |

### Medium

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| A-M1 | `frontend/src/types/index.ts:9/41` | `Conversation { createdAt: Date }` 与 `SessionResponse { created_at: string }` 字段名风格不统一 + 类型不一致,跨网络边界需 ad-hoc 转换。 |
| A-M2 | `useWsConnection.ts:42` | `useTauriWs + useWebSocket` 两个 hook 在 mount 时都被调,即使 disabled 分支也消耗 ref 内存。factory pattern 更整洁。 |
| A-M3 | `desktop/SettingsView.tsx:26` | `handleToggleDarkMode` 直接 `querySelector('.nexus-desktop').setAttribute('data-theme', 'dark')`,与 `useDarkModeRoot` MutationObserver 双源,React 重建根节点会丢属性。 |
| A-M4 | `useConversationCrud.ts:36-76` | `selectSessionRequestRef` race guard 设计对了,但 DELETE 失败仍乐观更新 UI → "鬼影会话"(子代理 SEVERE)。 |
| A-M5 | `ShellLayout.tsx` + `DesktopShell.tsx` | props 与 context 大量字段重叠(conversations/currentConvId/onSelectConv/onDeleteConv/onNewTask/wechatConnected),两套真值源。 |
| A-M6 | `db.py:107-130` `memory_legacy` 表 + 5 索引 | v0.2+ 完全孤儿,每新用户库白白占 5 索引 + 表结构初始化开销。回查通常用 Conversation 重组即可。 |

### Low

- `wechat_account.py / wechat_tokens.py / wechat_protocol.py` 三个相邻模块里都有同 prefix `_load_account / _list_indexed_weixin_account_ids`,导入依赖关系难 trace。
- `routes/model_config.py` 300 行,init_router 注入 4 个依赖,可在测试里丢掉 — 已发现但是还好。

## 维度 3:性能与并发(Performance)

### High

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| P-H1 | `frontend/src/components/ChatArea.tsx:567` | `displayMessages.map(msg => <ChatBubble ... />)` 无虚拟化 + `ChatBubble` 未 `React.memo`,每个 chunk 触发全列表重建 + ReactMarkdown 全解析。流式响应 30-60 chunks/s 时,长对话(>50 消息)将出现明显卡顿。 |
| P-H2 | `ChatArea.tsx:96` | `messagesRef.current.push(userMsg)` + 直接 mutate `last.thinking += ...` 是反模式 React state,**并发模式**下会与 commit phase 打架,产生 stale state(子代理 SEVERE)。 |
| P-H3 | `db.py:322` `find_latest_session_by_user` 全表扫 | 见 Q-H3,生产规模 messages 表 100k+ 行后单次查询 100-500ms。 |
| P-H4 | `main.py:415-420` 60s `wait_for(_agent_ready_event.wait())` | 首条 WS 消息 delay 上限 60s,如果 Agent + MCP 构造 70s,WS 客户端会重连风暴(axios / `useWebSocket` 重连无 maxRetries)。 |

### Medium

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| P-M1 | `useWebSocket.ts:95` | 重连退避 **无 jitter**,易多端同步重连撞代理/服务端。**无 maxRetries**,失败后无限循环(子代理 HIGH)。 |
| P-M2 | `desktop/Sidebar.tsx:39` | `sortedConversations` 不 memo,每次 render 都做 `[...conv].sort(new Date(...).getTime())`。 |
| P-M3 | `desktop/ContextMenuHost.tsx:14` | 3 个全局监听器(mousedown/keydown/scroll)在 menu 每次开都重绑,scroll 高频触发 cleanup/重建。 |
| P-M4 | `ChatArea.tsx:322` | `scrollIntoView({behavior:'smooth'})` 每个 chunk 都触发,流式 30s 内做 200+ 平滑滚动。 |
| P-M5 | `useStore.ts` `setConversationMessages` | 全量替换数组,即使只有一条新消息也整组 set,selector 在细粒度场景下不优。 |
| P-M6 | `ChatArea.tsx:289` `disarmWatchdogRef.current = disarmWatchdog` 在 render body 写 ref | Concurrent 模式下可能在 commit 前产生不一致快照。 |
| P-M7 | `wechat_channel.py:255` | `poll_interval = data["longpolling_timeout_ms"]/1000` 但设置后下一次循环才生效,如果服务端给的延迟值 < server poll interval 实际,会过度轮询。 |

### Low

- `desktop/hooks/useDarkModeRoot.ts` MutationObserver `subtree: true` 监听整个 body,react reconciler 触发的 mutation 都会触发回调。
- `wechat_login.py` 状态轮询固定 3s 间隔,与 fetch 实际耗时无关。

## 维度 4:安全与可靠性(Security & Reliability)

### High

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| S-H1 | `frontend/src/lib/api.ts:1` `DEFAULT_TOKEN='nexus-default-token'` | 默认 token 硬编码到 bundle,Webpack/Vite 静态替换。删之,改为启动 setup 强制覆盖或后端 challenge 派发。 |
| S-H2 | `frontend/src/components/ChatArea.tsx:299` + 后端 `main.py:402` | 双向契约:`?token=...` 作为 URL query,**全部走代理 access log / 浏览器历史 / 错误堆栈**。改 Sec-WebSocket-Protocol 或首帧携带。 |
| S-H3 | `frontend/src/components/desktop/SetupView.tsx:92` API key 尾 4 位明文写入剪贴板 | `apiKey.slice(-4)` 直接拼到 onContextMenu 复制文案,明文密钥前缀被复制 = 用户粘贴到错地方等于泄漏密钥。 |
| S-H4 | `frontend/src/components/desktop/SetupView.tsx:17` `saveModel` 无 response.ok 检查 | 4xx/5xx 也走 "配置已保存",`apiKey` / `temperature NaN` / `apiBase 畸形` 透传到后端入库。 |
| S-H5 | `db.py:322 LIKE` | 见 P-H3 — 既是性能问题也是潜在的跨用户内容泄漏(若 user_id 出现冲突)。 |

### Medium

| 项 | 文件:行 | 描述 |
| --- | --- | --- |
| S-M1 | `frontend/src/hooks/useTauriWs.ts:79` | `String(e)` 把 Rust 内部路径/栈帧透传给前端协议层,可能泄漏 Rust 内部组件信息到日志/UI。 |
| S-M2 | `gateway.py:96-198` | `route_message` 顶层 `except Exception as e` 兜底,然后调 `_send_error` 又有可能再次抛 — 兜底逻辑不够深。 |
| S-M3 | `fact_check.py:171-213` `_persist` 静默吞 DB 异常 | 设计取舍,但 audit trail 丢失时只 log warn,无可观测补偿。这意味 fact_check 失败的事实可以**长期** 被吞掉。 |
| S-M4 | `resilience/resume.py:193` | HMAC token 校验失败返回 "InvalidResumeToken" 但 token 仍是 `cx_Freeze/.app` 直读;建议加 nonce 防 replay。 |
| S-M5 | 前后端契约未文档化:`EventSink / NexusLogHandler / TextThinkingParser / StreamGuard` 等模块的 wire-level 行为只在 docstring,缺一个 `docs/protocol/wire.md`。 |
| S-M6 | `wechat_channel.py:34-39` | `_send_message` 错误只 log error,不通知用户;长轮询内部 `except Exception: sleep(poll_interval)` 一律吞,真实偶发错误丢失。 |

### Low

- `useLoadingWatchdog.ts:58` 把"模型账户限流"和"API key"等内部排障字串直接暴露给 UI 文案,i18n 后失真。
- `fact_check/verifiers.py` 任意正则表达式对 LLM 输出做匹配,无 rate-limit / 复杂度保护,恶意长输入会拖死中间件(DoS 风险)。

## 总结(7 条)

1. **架构合理**:`SPEC.md` 与代码高一致;3 次重构(WS 分层 / Channel C4 / HITL 中间件)做出来的边界都清晰可识别,只是部分组件略肥胖(ChatArea 813 行 / gateway 200 行混多职责)。
2. **安全债集中在前端**:`lib/api.ts` 默认 token、`ChatArea.tsx` 的 URL token、`SetupView.tsx` 的 API 密钥尾 4 位泄露 —— 这 3 个改动一年之内必须收回。
3. **WS 重连稳态有缺口**:`useWebSocket` 缺 maxRetries + jitter,生产场景面临重连风暴;后端 60s wait_for 上限没有客户端 timeout 配合。
4. **关键 P1 性能债**:`ChatArea` 的 mutate-ref + ChatBubble 无 memo 在长对话场景是真实风险;`db.find_latest_session_by_user` 全表扫是运营级别隐患。
5. **数据质量**:`db.list_sessions` Python 层 wechat 过滤 + 标题解析脆弱,加 `account_id` 列才稳;`memory_legacy` 孤儿 schema 可考虑加版本门控跳过初始化。
6. **测试覆盖现状**:因果 check pipeline 21 commits 后端覆盖已达 ~640 测试,backend 维度中无严重稳定性问题;前端 E2E 之前已覆盖主对话 / HITL / 设置 / 重连 / 微信 UI。
7. **最值得立即修的 5 项**(在 `plans/2026-07-12-high-value.md` 给出实施计划):
   - **安全**:WS token 改 subprotocol + 删硬编码默认 token + API 密钥截断禁止
   - **性能**:`ChatBubble` + memo + 虚拟列表;`db.find_latest_session_by_user` 加索引
   - **可靠**:`useWebSocket` 加 maxRetries + jitter + AbortController
   - **架构**:`useStore` 按 slice 拆分;`db.list_sessions` 改 SQL GROUP BY account_id
   - **可维护**:`ChatArea` 抽出 `handleWsMessage` 9 个 type-handler + 拆 `ClarificationForm` + 拆常量;`f-string` 日志改 lazy %s
