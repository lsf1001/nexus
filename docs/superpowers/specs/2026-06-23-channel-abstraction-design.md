# Nexus Channel 抽象层重构设计

**日期**：2026-06-23
**状态**：Draft（待用户审阅）
**作者**：Claude (brainstorming skill)
**目标**：把 Nexus IM 通道从"微信硬编码在 main.py 的 200 行"重构为"Gateway 真接管 + ChannelRegistry 唯一所有权 + Channel ABC 子类可插拔"的多通道架构。

---

## 1. 背景与动机

### 1.1 现状（5 文件硬耦合）

```
main.py (FastAPI 路由 + 200 行微信业务硬编码)
 ├─ _wechat_executor / _wechat_sessions / _main_loop / _wechat_sessions_lock
 ├─ _resolve_wechat_session(user_id)
 ├─ _handle_wechat_message()
 ├─ _process_wechat_message_sync() / _process_wechat_message()
 ├─ lifespan() 初始化 _wechat_sessions_lock
 └─ /api/channels/wechat/{qr,status,bind,unbind} × 5 个 REST endpoint

channels/wechat_channel.py:WeChatChannel
 ├─ start() / stop() / send_message()  (继承自 Channel ABC, OK)
 └─ _poll_messages → _handle_incoming_message → self._on_message_callback
    ↑ 不走 Channel._safe_handle_message → 不走 Gateway.route_message (旁路)

channels/gateway.py:Gateway (309 行, 0 caller)
 ├─ route_message() / _get_or_create_session() / _call_agent() / _send_response()
 └─ 写好了但没人调（微信旁路了它）

api/ws.py:handle_websocket(wechat_callback=...)  ← 槽位只为微信设计

backend/plugins/wechat_plugin.py (367 行)  ← 0 caller 孤儿, plugins/__init__.py 自导出自引用

backend/channels/wechat.py (110 行)  ← re-export 壳, 兼容老 import 路径
```

### 1.2 问题

1. **Gateway 写了 309 行但没人调用**，是设计失败的死代码。
2. **main.py 200 行微信专属业务逻辑**：加 Telegram / Slack 时再复制 200 行。
3. **`wechat_callback` 槽位只为微信设计**：加 Telegram 还得改 `api/ws.py:594-630`。
4. **`plugins/wechat_plugin.py` 367 行孤儿**：混淆"哪一套才是生产路径"。
5. **`wechat.py` 110 行兼容壳**：以后永远有"老路径/新路径"两份 import 认知负担。
6. **ChannelRegistry 几乎没人用**：构造了但只在 `/api/channels` GET 用一次。

### 1.3 决策记录（用户已确认）

| # | 决策 | 选择 |
|---|---|---|
| Q1 | Gateway 如何接管微信路由 | **改 Gateway, 微信接入它** |
| Q2 | wechat.py 兼容层 | **彻底删** |
| Q3 | plugins/wechat_plugin.py 孤儿 | **删** |
| Q4 | ChannelRegistry 角色 | **作为唯一所有权** |
| Q5 | api/ws.py wechat_callback 参数 | **改为 channel_broadcasts dict** |
| Q6 | 灰度策略 | **一步到位**（出问题 git revert） |
| Q7 | 前端变更范围 | **前端也要重构**（后端 + 前端一次提交） |
| 方案 | A/B/C | **A 彻底多通道架构** |

---

## 2. 目标

1. **今天加 Telegram 只新增 1 个 channel.py + 1 个 .tsx**，其他 0 改动。
2. **main.py 不再有 IM 业务逻辑**，只剩路由壳 + lifespan 注入。
3. **Gateway 真接管所有 channel 的消息路由**，`_call_agent` 是所有通道共用的 runner。
4. **ChannelRegistry 是 channel 的唯一 owner**，取代 `get_active_wechat_channel` / `_wechat_sessions` 等散落全局状态。

---

## 3. 架构（3 层 + 唯一所有权）

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — Transport (FastAPI, 只剩路由壳)                         │
│                                                                   │
│  main.py                                                          │
│   ├─ /api/ws                   → ws.handle_websocket(channel_broadcasts=...) │
│   ├─ /api/channels             → channel registry list/status    │
│   ├─ /api/channels/wechat/...  → 微信专属 endpoint (绑/扫码/解绑)│
│   └─ lifespan()                → 初始化 Gateway + Registry       │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2 — Routing (Gateway 真接管)                                │
│                                                                   │
│  channels/gateway.py:Gateway                                      │
│   ├─ register_channel(ch)         ← Registry 转调                 │
│   ├─ set_broadcast(ch_type, fn)   ← WS 客户端连接时注入           │
│   ├─ route_message(msg)                                            │
│   │    1. _get_or_create_session(msg) (走 db.find_latest_...)    │
│   │    2. db.add_message(user, msg)                                │
│   │    3. _call_agent(prompt) ← 抽出的共用 runner                  │
│   │    4. db.add_message(assistant, response)                     │
│   │    5. channel.send_message(response_msg)                       │
│   │    6. broadcast[ch_type](response_msg)                         │
│   └─ unregister_channel / get_channel_status                      │
│                                                                   │
│  channels/registry.py:ChannelRegistry                             │
│   └─ 唯一 ownership, 取代 _wechat_sessions / get_active_wechat_channel │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3 — Adapters (Channel ABC 子类)                             │
│                                                                   │
│  channels/wechat_channel.py:WeChatChannel                         │
│   ├─ start/stop/send_message (from Channel ABC)                  │
│   ├─ _poll_messages (35s 长轮询, 不变)                             │
│   └─ _handle_incoming_message(raw) → Channel._safe_handle_message │
│                                                                   │
│  (未来 telegram_channel.py: 同上结构, 只改 _poll + 内容解析)        │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 关键不变量

| # | 不变量 | 谁保证 |
|---|---|---|
| 1 | 同一 channel_type 的多个实例由 ChannelRegistry 索引 | `registry.start_channel()` |
| 2 | 用户消息进 → Agent 跑 → 出 必须经过 Gateway | `Channel._safe_handle_message` 唯一入口 |
| 3 | WS 客户端看到所有 channel 的回复 | `channel_broadcasts: dict[ChannelType, Callable]` |
| 4 | main.py 不再有 IM 业务逻辑 | 只剩 5 个 endpoint + lifespan 注入 |

---

## 4. 接口契约

### 4.1 Channel ABC（基类契约）

```python
class Channel(ABC):
    """所有 IM 适配器继承此接口。

    契约：
      - start(): 启动后台轮询 / 长连接 / webhooks, 开始接收消息。
      - stop():  停止接收, 清理连接和后台任务。
      - send_message(msg: ChannelMessage): Gateway 调用, 把 Agent 回复发回 IM。
      - 所有收到的 IM 消息必须构造 ChannelMessage 后调 self._gateway.route_message()
        (Channel 基类提供的 _safe_handle_message 是推荐入口, 自带异常隔离)。
    """
    def __init__(self, config: ChannelConfig):
        self.config = config
        self.state = ChannelState(...)
        self._gateway: Gateway | None = None   # 由 Registry.register_channel 注入
        self._lock = asyncio.Lock()

    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def send_message(self, msg: ChannelMessage) -> None: ...
```

### 4.2 Gateway（路由契约）

```python
class Gateway:
    """IM 消息的中央路由。"""

    def __init__(self, *, agent, sessions_module, messages_module):
        self._agent = agent
        self._sessions = sessions_module
        self._messages = messages_module
        self._channels: dict[str, Channel] = {}
        self._session_to_channel: dict[str, str] = {}
        self._user_to_session: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._broadcasts: dict[ChannelType, Callable[[ChannelMessage], Awaitable[None]]] = {}

    def register_channel(self, ch: Channel) -> None:
        ch.bind_gateway(self)
        self._channels[ch.config.channel_id] = ch

    def set_broadcast(self, ch_type: ChannelType, fn: Callable) -> None:
        """由 WS 客户端连接时调(api/ws.py handle_websocket),把消息广播给前端。
        同一 channel_type 多次连接会覆盖前一个 broadcast fn(WS 端生命周期)。
        """
        self._broadcasts[ch_type] = fn

    async def route_message(self, msg: ChannelMessage) -> None:
        async with self._lock:
            session_id = await self._get_or_create_session(msg)
        await self._messages.add_message(uuid4(), session_id, "user", msg.content)
        try:
            prompt = self._sessions.build_prompt(session_id, msg.content)
            response_text = await self._call_agent(prompt)
        except Exception as e:
            await self._send_error(msg, str(e))
            return
        if response_text:
            await self._messages.add_message(uuid4(), session_id, "assistant", response_text)
            ch = self._channels.get(msg.channel_id)
            if ch:
                await ch.send_message(self._build_response(msg, response_text))
            broadcast = self._broadcasts.get(msg.channel_type)
            if broadcast:
                await broadcast(self._build_broadcast(msg, response_text))

    async def _call_agent(self, prompt: dict) -> str:
        """抽出来的 runner 共用段(stream_mode='updates' 累积 model chunk + 去思考段标签)。"""
        full = ""
        async for chunk in self._agent.astream({"messages": prompt["messages"]}, stream_mode="updates"):
            if isinstance(chunk, dict) and "model" in chunk:
                msgs = chunk["model"].get("messages", []) if isinstance(chunk["model"], dict) else []
                for m in msgs:
                    c = getattr(m, "content", "") or ""
                    if c:
                        full += c
        # 去 deepagents 模型产生的 &lt;think&gt; / &lt;/think&gt; 思考段标签 (原 main.py:223)
        return full.replace("&lt;think&gt;", "").replace("&lt;/think&gt;", "").strip()
```

### 4.3 ChannelRegistry（唯一所有权契约）

```python
class ChannelRegistry:
    """所有 Channel 实例的唯一 owner。"""

    def __init__(self, gateway: Gateway):
        self._gateway = gateway
        self._channels: dict[str, Channel] = {}
        self._by_type: dict[ChannelType, list[str]] = {}

    async def start_channel(self, config: ChannelConfig, **kwargs) -> Channel:
        ch = create_channel_from_config(config, **kwargs)
        self._gateway.register_channel(ch)
        self._channels[ch.config.channel_id] = ch
        self._by_type.setdefault(config.channel_type, []).append(ch.config.channel_id)
        await ch.start()
        return ch

    async def stop_channel(self, channel_id: str) -> None: ...
    def get(self, channel_id: str) -> Channel | None: ...
    def get_active_by_type(self, ch_type: ChannelType) -> Channel | None:
        """取该类型第一个 RUNNING 通道。"""
        for cid in self._by_type.get(ch_type, []):
            ch = self._channels.get(cid)
            if ch and ch.state.status == ChannelStatus.RUNNING:
                return ch
        return None

    def list_all(self) -> list[Channel]: ...
    async def stop_all(self) -> None: ...
```

---

## 5. 文件级改动清单

### 5.1 新增 (6)

- `tests/test_gateway.py`（Gateway 单测，含 mock channel + agent）
- `tests/test_gateway_session_lock.py`（并发 session 创建测试）
- `tests/test_channel_registry.py`（注册/注销/查重）
- `frontend/src/components/desktop/channels/ChannelViewBase.tsx`（基类）
- `frontend/src/components/desktop/channels/ChannelInbox.tsx`（共享收件箱）
- `tests/test_wechat_channel_uses_gateway.py`（微信走 Gateway 不走 callback）

### 5.2 修改 (10)

- `nexus/backend/channels/gateway.py`（重写 `_get_or_create_session` 走 `db.find_latest_session_by_user`，重写 `_call_agent`，加 `set_broadcast`）
- `nexus/backend/channels/wechat_channel.py`（删 `on_message` 旁路，改为 `_safe_handle_message`）
- `nexus/backend/channels/registry.py`（删 WEBSOCKET 分支，加 `start_channel`/`stop_channel`/`get_active_by_type`）
- `nexus/backend/channels/base.py`（删 `ChannelType.WEBSOCKET`）
- `nexus/backend/main.py`（删 `_wechat_*` 全局 + 5 个 `_handle_*` 函数；lifespan 注入 Gateway + Registry）
- `nexus/backend/api/ws.py`（`wechat_callback: Callable` → `channel_broadcasts: dict[ChannelType, Callable]`）
- `frontend/src/components/desktop/WechatAssistantView.tsx`（继承 `ChannelViewBase`）
- `frontend/src/types/index.ts`（`wechat_message` 改 `channel_message` + `channel_type` 字段）
- `frontend/src/components/desktop/Sidebar.tsx`（新增 Channels section）
- `frontend/src/components/desktop/DesktopShell.tsx`（`<WechatAssistantView />` 替换为 `<ChannelsPanel />`）

### 5.3 删除 (3)

- `nexus/backend/channels/wechat.py`（110 行 re-export 壳）
- `nexus/backend/plugins/wechat_plugin.py`（367 行孤儿）
- `nexus/backend/plugins/__init__.py`（清空 `wechat_plugin` 引用，保留 `define_channel_plugin_entry`）

---

## 6. 错误处理矩阵

| 失败场景 | 当前行为 | 重构后行为 | 谁负责 |
|---|---|---|---|
| Agent.astream 抛异常 | logger.error, 整条微信消息丢失 | Gateway catch → ch.send_message(error_msg) + log | Gateway._call_agent |
| DB 落库失败 | main.py 没有 try/except, 直接 raise | Gateway 落库 try/except + log, 不影响后续 send | Gateway._save_message |
| ch.send_message 失败 | 无 try/except | Gateway._send_response try/except, 只 log | Gateway._send_response |
| broadcast (WS 推送) 失败 | try/except 已有 | Gateway.set_broadcast 调用处 try/except | Gateway.route_message |
| 同一 user_id 并发消息 | main.py `_wechat_sessions_lock` | Gateway._get_or_create_session 内 `async with self._lock` | Gateway |
| session 在 DB 已删 | fallback 到 DB 重建 | Gateway 落库前 `get_session(existing)` 校验 | Gateway |
| 微信 session 过期 (-14) | wechat_channel.py `_pause_session` 1 小时 | 不变 | WeChatChannel |

**关键原则**：所有 catch 都 log + 不冒泡（除非 user-visible 错误必须回送）。

---

## 7. 测试覆盖

### 7.1 后端（pytest）

| 测试文件 | 覆盖点 |
|---|---|
| `test_gateway.py::TestRouteMessage` | 正常路径 4 步全跑通 |
| `test_gateway.py::TestRouteMessageError` | agent raise → _send_error |
| `test_gateway.py::TestRouteMessageEmptyContent` | 空 content 早 return |
| `test_gateway.py::TestSessionLock` | 同 user_key 并发 10 个只创建 1 个 session |
| `test_gateway.py::TestSessionResumed` | DB 已有 session → 复用 |
| `test_gateway.py::TestBroadcastIsolated` | broadcast raise 不影响 send |
| `test_gateway.py::TestCallAgentStripThinking` | 输出不含 `&lt;think&gt;` 思考段标签 |
| `test_channel_registry.py::TestStartChannel` | start_channel 后状态 RUNNING |
| `test_channel_registry.py::TestStopChannel` | stop_channel 清理 _channels + _by_type |
| `test_channel_registry.py::TestGetActiveByType` | RUNNING 才返回 |
| `test_channel_registry.py::TestDuplicateStart` | 同一 type 已 RUNNING 时再 start 抛 ValueError |
| `test_wechat_channel_uses_gateway.py` | WeChatChannel._handle_incoming_message 走 _safe_handle_message |
| `test_wechat_smoke.py`（保留） | 13 用例, wechat_*.py 8 模块拆分 |
| `test_e2e_features.py`（保留） | 端到端真实 LLM |

### 7.2 前端（vitest）

| 测试文件 | 覆盖点 |
|---|---|
| `ChannelViewBase.test.tsx` | 传 channelType="wechat" 渲染 WechatAssistantView 子组件 |
| `ChannelInbox.test.tsx` | 收 `channel_message` 帧按 channel_type 过滤 |
| `useChannelStatusPolling.test.ts` | 传 "wechat" 调 `/api/channels/wechat/bind` |

### 7.3 手动冒烟

```bash
# 1. 启动后端
python -m nexus.backend.run &
while ! curl -fs http://localhost:30000/health; do sleep 1; done

# 2. 启动前端
cd frontend && npm run dev &

# 3. 微信扫码登录 → status=running
# 4. 微信发消息 → 前端 inbox 显示 + agent 回复
# 5. 多通道隔离: 无 WS 客户端, 微信发消息仍正常 (broadcast 已注册但无消费者)
# 6. 错误路径: 杀 agent 进程 → 发微信 → 用户收到 "处理消息时出错"
```

---

## 8. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Gateway._call_agent 抽错（漏去 `&lt;think&gt;` 标签） | 中 | 高 | `TestCallAgentStripThinking` 单测 |
| 会话并发锁死锁 | 低 | 高 | `TestSessionLock` 单测 + 只用一把 lock |
| wechat.py 删除漏 import | 高 | 中（启动 ImportError） | grep `from .channels.wechat` 必须 0 命中 |
| 前端帧 type 不匹配 | 高 | 中 | 一次性提交前后端; 不留中间态 |
| 微信 session 重建丢历史 | 低 | 高 | _get_or_create_session 一次性完成, 失败 raise |
| plugins/wechat_plugin.py 删除漏 import | 中 | 中 | `git grep "from .wechat_plugin"` 0 命中 |
| 微信重启后内存状态丢失 | — | — | 行为兼容, 启动时按 user_id 重建 |

## 9. 回滚策略

Q6 决定一步到位。回滚手段只有 **git revert**：

```bash
# 重构前打 tag 作安全点
git tag refactor-pre-channel-arch

# 出问题回滚
git revert HEAD
# 或:
git revert <commit-1> <commit-2> ...
```

---

## 10. Commit 顺序（6 个原子 commit）

每个 commit 单独 `pytest + ruff` 全过后才进下一个。

```
C1. refactor(backend): 删 plugins/wechat_plugin.py + plugins/__init__.py 清空
C2. refactor(channels): 删 wechat.py re-export 壳 + 20+ import 站点直连细分模块
C3. refactor(channels): ChannelRegistry 升级为唯一所有权 + 新增 start_channel/stop_channel/get_active_by_type
C4. refactor(backend): Gateway 真接管路由 + WeChatChannel 走 _safe_handle_message + main.py 删 _wechat_* 全局
C5. refactor(frontend): types 加 channel_message 帧 + 新建 ChannelViewBase/ChannelInbox + WechatAssistantView 子类化
C6. feat(backend): base.py 删 ChannelType.WEBSOCKET (前端 WS 不走 Channel ABC)
```

**总改动量**：14 文件 + ~1500 行变更（含测试）。
**总时间预算**：4-6 小时。

### 10.1 验收标准

每个 commit 前自检：
```bash
pytest tests/ -q --ignore=tests/test_e2e_features.py   # 全过
ruff check . && ruff format --check .                   # 0 error / 0 diff
```

C4 后必须手动冒烟（扫码登录 + 收发）。
C6 最终全量（E2E + frontend lint + frontend test）。

---

## 11. 失败处理

| 失败 | 行动 |
|---|---|
| C1 删 wechat_plugin 后 import error | `git grep "wechat_plugin"` 找漏点补 import |
| C2 删 wechat.py 后 import error | `git grep "from .channels.wechat"` 应已 0 命中 |
| C3 registry 单测 fail | 不影响 main.py (未迁移), 重写 registry 实现 |
| C4 Gateway 单测 fail | **不前进**, 先修 |
| C4 手动冒烟微信发消息无响应 | `tail -f ~/.nexus/logs/nexus-backend.log` 看 `Gateway.route_message` log |
| C5 前端 lint fail | 改代码直到 0 error |
| C6 E2E fail | **不前进**, E2E 是真实 LLM 端到端, 失败说明有更深层问题 |
| 任何 commit 后 `git status` 出现意外文件 | `git reset HEAD` + 检查 |

---

## 12. 不在范围内

为避免范围蔓延, 以下功能**本次不做**:

1. **真实接入 Telegram/Slack/Feishu** — 抽象就位, 真接留给以后
2. **Gateway 持久化** — 当前 in-memory `_user_to_session`, 重启丢失行为不变
3. **broadcast 多 consumer** — 当前每 channel_type 只 1 个 broadcast fn (WS)
4. **Channel hot reload** — 当前 registry 只在 lifespan 构造, 不支持运行时新增 channel_type
5. **多账号微信** — 当前微信单一账号, 复用 wechat_login 多账号能力但不改抽象层

---

## 13. 验证（设计完成后, 实现时跑）

```bash
# 1. 静态检查
source .venv/bin/activate
ruff check . && ruff format --check .    # 0 error / 0 diff

# 2. 测试套件
pytest tests/ -q                          # 全部通过
cd frontend && npm run lint && npm run test

# 3. 死代码清扫（必须 0 命中）
git grep -n "from .channels.wechat" nexus/ tests/   # → 0
git grep -n "wechat_plugin" nexus/ tests/             # → 0
git grep -n "_wechat_sessions\b" nexus/                # → 0
git grep -n "get_active_wechat_channel" nexus/         # → 0
git grep -n "_handle_wechat_message" nexus/            # → 0
git grep -n "_process_wechat_message" nexus/           # → 0

# 4. 手动冒烟
python -m nexus.backend.run &
curl -fs http://localhost:30000/health
# 扫码登录 + 收发消息 + 前端 inbox 显示
```
