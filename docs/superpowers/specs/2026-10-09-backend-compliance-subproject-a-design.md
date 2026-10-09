# Sub-project A:Backend Middleware + Write_Tools 保护 合规重构

> **目的**:在保证 1082 个既有测试全过(行为基线零破坏)的前提下,完成 21 个
> 合规 finding 中属 sub-project A 的 11 项,覆盖 backend middleware / write_tools
> 防护 / WS 鉴权 / 状态管理 / 评估 / 日志。
>
> **范围**:sub-project A 涵盖的代码 + 测试
> (`nexus/backend/{main,db,app_state,launcher}.py` /
>  `nexus/backend/{db,api/ws,fact_check}/` package /
>  `nexus/backend/llm/wrapper.py` /
>  `nexus/backend/{permissions,agents/middleware,fact_check}/` /
>  既有 + 新增测试)。
> **不在范围**:frontend、desktop、e2e、docs 文档(属 sub-projects C/D/E);
> agent / tools / skills / wrapper 内部实现(属 sub-project B);
> 纯文档/脚本/conftest(属 sub-project E)。
>
> **前置报告**:
> - [`docs/operations/deepagents-0.7.23-alignment.md`](../operations/deepagents-0.7.23-alignment.md)
> - [`docs/superpowers/plans/2026-10-09-deepagents-0.7.23-upgrade.md`](../superpowers/plans/2026-10-09-deepagents-0.7.23-upgrade.md)
>
> **合规基线**:本文件由 sub-project A 的 brainstorming session 生成,完整设计
> 分 §1 架构与边界 / §2 数据流与错误处理 / §3 组件与公开 API / §4 测试策略 /
> §5 风险与执行 5 节。

## §1 架构与边界

### 1.1 三类边界

| 边界 | 现有文件 | 改造后 |
|---|---|---|
| **WS 鉴权 + 流式 + HITL** | `api/ws/auth.py` (P0-1 query fallback 默认 ON) + `api/ws/streaming.py` (889 行) | `api/ws/auth.py`(P0-1 关 query fallback)+ `api/ws/streaming.py`(瘦身至 ≤800) + 新增 `api/ws/streaming_hitl.py`(HITL 状态机) |
| **Agent 生命周期 + DB** | `main.py` (851 行) + `db.py` (819 行) | `main.py`(瘦至 ≤800) + 新增 `app_state.py`(frozen dataclass) + `db.py` 拆为 `db/{__init__,quality_schema}.py` package |
| **评估 + 日志** | `fact_check/verifiers.py` + `agents/middleware/fact_check.py`(两处入口) + `llm/wrapper.py`(缺返回类型) + `launcher.py`(print 替代 logger) | 新增 `fact_check/__init__.py`(统一入口) + `verifiers.py` + middleware 改 import 入口 + `wrapper.py` 加 `-> Any` + `launcher.py` 改 logger |

### 1.2 核心原则

1. **不引入新抽象层** —— YAGNI;只重构已有逻辑,不改外部行为
2. **测试 = 合约** —— 现有 1082 个测试就是行为基线;任何破坏 = 立即回滚
3. **拆文件按职责不按行数** —— 不是机械拆,而是按"职责是否独立"拆

## §2 数据流与错误处理

### 2.1 WS 请求生命周期

```
客户端 → FastAPI WS endpoint(/api/ws)
    1. auth: Sec-WebSocket-Protocol header 校验(query fallback 默认关)
        失败 → 401 close,logger.warning 记 token 长度(不记内容)
    2. 接帧: token / message / interrupt_decision
    3. streaming.py(stream_mode="updates"):
        a. agent.astream(input_dict) 生成 chunk
        b. HITL: detect GraphInterrupt → 中断流 → HITLInterrupter 等 WS 帧 decision
        c. WS 帧 decision 到达 → resume → 继续流
        d. final → done 帧
    4. 异常: WS 帧 protocol_error → close 1008;不抛到外层
```

### 2.2 Agent 启动(lifespan 一次性)

```
lifespan(app):
    1. AppState 初始化(frozen dataclass)
        main_loop = asyncio.get_running_loop()
        mcp_tools = await load_all_mcp_tools()  ← 不阻塞主线程
        db_conn = init_db_conn(pragmas: foreign_keys=ON, journal_mode=WAL, synchronous=NORMAL)
    2. agent = create_deep_agent(tools=..., middleware=...)
    3. yield  ← AppState 在 app.state 持有
```

### 2.3 DB 写入路径

```
session.message.write
    ↓
db.get_conn()
    ↓
db.write 中自动 _ensure_column(新列 ALTER TABLE ADD COLUMN)
    ↓
PRAGMA foreign_keys=ON / journal_mode=WAL
    ↓
COMMIT
```

### 2.4 错误处理(对齐 python_project.md §1.6)

| 场景 | 处理 |
|---|---|
| **WS 鉴权失败** | 401 close,不抛到外层,logger.warning 记 token 长度 |
| **流式中断**(GraphInterrupt) | 静默(预期路径),不写 ERROR |
| **流式异常** | catch Exception → WS 帧 protocol_error → close 1008,logger.exception 记上下文,**粗粒度**,不带 token hash |
| **MCP 加载失败** | lifespan 启动失败 → 抛 + 退出,**不静默吞**(改 P0-2) |
| **DB 连接失败** | retry 3 次后抛,带 PRAGMA 验证日志 |
| **fact_check 单 verifier 失败** | 跳过该 verifier,继续下一个;最终 score 用剩余 verifier 加权归一化,不抛 |
| **launcher 启动异常** | logger.exception("launcher startup failed") + exit code,**不用 print** |

### 2.5 错误日志规范(改 P1-5)

- ❌ `logger.error(f"failed: {e}")` → f-string 提前求值
- ✅ `logger.error("failed: %s", e)` → 延迟格式,带 traceback 时不重复格式化

### 2.6 不动的事(CLAUDE.md 硬约束)

- **`models.json` 写入仍走 `models_config.save_models()`**
- **`memory_legacy` 表只读**
- **`QualityGateMiddleware` 拦截写受保护 AGENTS.md**
- **WS 跨线程桥接走 `run_coroutine_threadsafe`,禁止子线程直接 await**

## §3 组件与公开 API

### 3.1 新增模块

| 路径 | 角色 | 行数目标 |
|---|---|---|
| `nexus/backend/app_state.py` | `AppState` 不可变 dataclass,持有 main_loop / agent / mcp_tools / db 句柄 | ≤60 |
| `nexus/backend/db/__init__.py` | 替代 db.py,顶层 re-export 所有公开符号,`init_db()` / `get_conn()` / `ensure_column()` / `get_health()` | ≤150 |
| `nexus/backend/db/quality_schema.py` | `QualityScoreRepo` 类,quality_scores 表 CRUD | ≤150 |
| `nexus/backend/api/ws/streaming_hitl.py` | `HITLInterrupter` 类,GraphInterrupt 状态机 + WS 帧路由 + resume 衔接 | ≤200 |
| `nexus/backend/fact_check/__init__.py` | 统一入口 `verify(claim, *, context) -> VerifyResult` | ≤80 |

### 3.2 AppState(frozen dataclass,5 字段)

```python
@dataclass(frozen=True)
class AppState:
    main_loop: asyncio.AbstractEventLoop
    agents: MappingProxyType[str, Any]  # name → CompiledStateGraph
    mcp_tools: tuple[Any, ...]          # 不可变
    db_conn: aiosqlite.Connection
    started_at: datetime
```

**关键约束**:
- `@dataclass(frozen=True)` —— 运行时不可改
- `agents` 用 `MappingProxyType` 包裹防外部改
- **不加** `shutdown_event: asyncio.Event`(FastAPI 原生 lifespan exit 足够)
- 启动期创建唯一一次,lifespan 持有引用

**不包含**:logger / 临时变量 / 锁(避免生命周期泄漏)

### 3.3 db/quality_schema.py(QualityScoreRepo)

```python
class QualityScoreRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None: ...
    async def upsert(self, *, message_id: str, score: float, breakdown: dict) -> None: ...
    async def get_latest(self, message_id: str) -> QualityScore | None: ...
    async def list_for_session(self, session_id: str, *, limit: int = 50) -> list[QualityScore]: ...
    async def average(self, session_id: str) -> float | None: ...
```

**行为边界**:
- **不**做 schema 迁移(`db/__init__.py` 负责 `_ensure_column`)
- **不**直接开新连接(用构造注入的 `conn`)
- **不**做格式化输出(返回 dataclass `QualityScore`)
- **不**拼 SQL 字符串(强制参数化 `?`)

### 3.4 fact_check/__init__.py(加权统一入口)

```python
@dataclass(frozen=True)
class VerifyResult:
    score: float
    claims_verified: int
    claims_failed: int
    reasons: tuple[str, ...]

async def verify(claim: str, *, context: Mapping[str, Any] | None = None) -> VerifyResult:
    """统一入口:遍历所有 registered verifier,加权计算最终 score。

    单 verifier 失败:
      - 静默跳过 + 记 logger.debug
      - 剩余 verifier 权重归一化后再加权
      - 若全部 verifier 失败,score=0.0,reasons=("all_verifiers_failed",)
    """
```

**加权算法**:

```python
total_weight = 0.0
weighted_sum = 0.0
for v in verifiers:
    try:
        score = await v.verify(claim, context)
        w = v.weight  # class-level 配置
        weighted_sum += w * score
        total_weight += w
    except (VerifierError, asyncio.TimeoutError) as e:
        logger.debug("verifier %s failed: %s", v.name, e)
        continue

if total_weight == 0:
    return VerifyResult(score=0.0, claims_verified=0, claims_failed=0,
                        reasons=("all_verifiers_failed",))
return VerifyResult(score=weighted_sum / total_weight, ...)
```

### 3.5 api/ws/streaming_hitl.py(HITLInterrupter)

```python
class HITLInterrupter:
    """GraphInterrupt 状态机。持有当前 stream_id,等 WS 帧 decision。"""

    def __init__(self, ws: WebSocket, *, timeout: float = 300.0) -> None: ...
    async def __aenter__(self) -> HITLInterrupter: ...
    async def __aexit__(self, *exc_info) -> None: ...

    async def wait_decision(self, interrupt: GraphInterrupt) -> Decision:
        """收 WS 帧(approve/edit/reject/respond),timeout 走 reject。"""
        ...
```

**行为边界**:
- **不**直接调 LLM(只做 WS 帧收发 + GraphInterrupt 解析)
- **不**写日志到外层(只让 logger.debug 记内部状态)
- **不**持有 agent 引用(只持有 ws + timeout)
- **不**入子线程路径(纯 async 协程)

### 3.6 既有文件改造

| 文件 | 行数 | 改造 |
|---|---|---|
| `main.py` | 851 → ≤800 | 抽 `lifespan` 装配到 `app_state.py`;`lifespan` 留 ~30 行 |
| `db.py` | 819 → 0(拆为 package) | `db.py` 删除,业务迁 `db/__init__.py`,quality_scores 迁 `db/quality_schema.py` |
| `api/ws/auth.py` | — | P0-1:query fallback 默认关,不动 env gate |
| `api/ws/streaming.py` | 889 → ~700 | 抽 HITL 状态机到 `streaming_hitl.py`;留流式推送 + 帧序列化 |
| `llm/wrapper.py` | — | 加 `-> Any` 返回类型到 `_generate` / `_stream` / `_astream` |
| `launcher.py` | — | `print(...)` → `logger.info(...)`;启动异常 `print(exc)` → `logger.exception(...)`;控制台保留 `print` 一行保底(PyInstaller 打包防 console 乱码) |
| `fact_check/verifiers.py` | — | 改 import 入口:从 `nexus.backend.fact_check` 取 `verify()` |
| `agents/middleware/fact_check.py` | — | 改 import 入口:同上 |

### 3.7 改造依赖图

```
main.py
  ├── app_state.py (new) ──── api/ws/auth.py
  │                       └── api/ws/streaming.py ──── api/ws/streaming_hitl.py (new)
  ├── db/ (new package)
  │   ├── __init__.py (re-export from db.py)
  │   └── quality_schema.py (new)
  ├── fact_check/__init__.py (new) ← verifiers.py + middleware/fact_check.py 改 import
  ├── llm/wrapper.py (annotate only)
  └── launcher.py (logger only)
```

## §4 测试策略

### 4.1 既有合约(测试 = 合约,基线 1082 passed / 12 skipped / 0 failed)

**与本子项目相关的既有测试**(改后必须仍全过):

- `tests/test_write_tools_helper.py`(15 个)—— 锁 `is_write_tool` / `_FS_TOOL_ORDER`,**不许改**
- `tests/test_ws_resilience.py` —— WS 鉴权 / retry / resume / 异常
- `tests/test_db_schema.py` —— db.py 行为基线
- `tests/test_quality_scores.py` —— quality_scores 表 CRUD
- `tests/test_fact_check.py`(8 个估算)—— 现有 verifier 行为
- `tests/test_streaming.py` + `tests/test_hitl.py` —— 流式 + HITL 状态

### 4.2 新增测试(24 个,本轮加)

| 测试文件 | 个数 | 覆盖 |
|---|---|---|
| `tests/test_app_state.py` | 4 | frozen 性质 / 字段访问 / MappingProxyType 不可变 / 启动一次 |
| `tests/test_db_quality_schema.py` | 6 | upsert / get_latest / list_for_session / average / 不持连接 / 参数化 SQL |
| `tests/test_fact_check_weighted.py` | 5 | 单 verifier / 多 verifier 加权 / 1-N 失败归一化 / 全失败 0.0 / TimeoutError 计入失败 |
| `tests/test_streaming_hitl.py` | 6 | approve / edit / reject / respond / timeout 走 reject / 异常帧 |
| `tests/test_ws_auth_query_off.py` | 3 | query fallback 默认拒绝 / env 未设也拒绝 / 错 token 拒绝 |

**改完后总测试数 = 1082 + 24 = 1106 个**(12 skip 不变)。

### 4.3 回归验证矩阵(改完必跑)

```bash
# 1. 静态检查
ruff check nexus/ tests/
ruff format --check nexus/ tests/

# 2. 既有合约(不能破)
pytest tests/test_write_tools_helper.py -v     # 15/15
pytest tests/test_ws_resilience.py -v          # all
pytest tests/test_db_schema.py -v              # all
pytest tests/test_quality_scores.py -v         # all
pytest tests/test_fact_check.py -v             # all
pytest tests/test_streaming.py tests/test_hitl.py -v  # all

# 3. 新增合约
pytest tests/test_app_state.py -v              # 4/4
pytest tests/test_db_quality_schema.py -v      # 6/6
pytest tests/test_fact_check_weighted.py -v    # 5/5
pytest tests/test_streaming_hitl.py -v         # 6/6
pytest tests/test_ws_auth_query_off.py -v      # 3/3

# 4. 全量
pytest tests/ -q --tb=line
# 期望 1106 passed, 12 skipped, 0 failed

# 5. 烟雾启动
source .venv/bin/activate
python -c "from nexus.backend.main import app; print('OK', len(app.routes))"
```

### 4.4 测试原则

- **每改一个模块,先跑该模块测试 + 直接依赖模块测试,再跑全量**
- **不改既有测试的断言**(只允许改 import 路径以适应新结构)
- **新测试不写 happy path 走过场**——必须有 1 个失败 / 边界用例
- **不 mock 内部 helper**——直接构造真实对象(mock 只对外部 IO)

### 4.5 不在本轮做

- E2E(Playwright)—— sub-project A 不动前端
- 性能压测 —— 重构是同构替换,性能不在合约
- mypy strict —— 本项目未启用

### 4.6 改文件 / 增文件 / 改测试 三类分清楚

| 类型 | 文件 |
|---|---|
| **改** | `main.py` / `db.py`(拆后删)/ `streaming.py` / `auth.py` / `wrapper.py` / `launcher.py` / `fact_check/verifiers.py` / `agents/middleware/fact_check.py` |
| **增** | `app_state.py` / `db/__init__.py` / `db/quality_schema.py` / `streaming_hitl.py` / `fact_check/__init__.py` + 5 个新测试文件 |
| **改测试 import** | 引用旧 `db.py` 路径的测试改为 `nexus.backend.db` package 路径 |

## §5 风险与执行

### 5.1 风险表

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| 1 | `db.py` 拆 package 后,旧 `import nexus.backend.db` 路径失效 | **P0** | `db/__init__.py` 顶层 re-export,全仓 import 路径全改前 import 路径兼容 |
| 2 | `streaming.py` 拆 HITL 状态机后,流式推送帧序列错位 | **P0** | `test_streaming.py` + `test_hitl.py` 全过;e2e 跑 `/api/ws` smoke |
| 3 | `AppState` frozen 引入后,某处悄悄 mutate 报错 | **P1** | `test_app_state.py::test_frozen` 显式 assert;grep `app_state.` 排查 |
| 4 | fact_check 加权算法引入后,既有 `test_fact_check.py` 期望旧 score | **P1** | 改前读 8 个测试,确认 score 算法是 sum 还是 weighted;新算法 + test 兼容 |
| 5 | `streaming_hitl.py` 用 `asyncio.timeout` 跨子线程 | **P1** | 本模块**纯** async 协程,不入子线程路径;CLAUDE.md 硬约束 |
| 6 | `launcher.py` 改 logger 后,PyInstaller 打包控制台输出格式变 | **P2** | logger 配置走 `~/.nexus/logs/launcher.log`,控制台仍走 `print` 一行保底 |
| 7 | `db/quality_schema.py` 抽类后,`upsert` SQL 拼字符串埋注入 | **P2** | 强制参数化 `?`;`test_db_quality_schema.py` 加恶意输入 case |
| 8 | `wrapper.py` 加 `-> Any` 后,mypy strict 模式开就报 | **P2** | 项目未启用 mypy strict,不动;留 issue |
| 9 | `app_state.py` 的 `MappingProxyType` 在 3.11 性能 | **P2** | 启动期一次性,性能可忽略 |

### 5.2 改动顺序(commit 序列,7 个 commit)

```
#1  feat(db): 拆 db.py 为 db/ package, quality_schema.py 抽 QualityScoreRepo
    ├── 新增 nexus/backend/db/__init__.py
    ├── 新增 nexus/backend/db/quality_schema.py
    ├── 改 nexus/backend/db.py → re-export shim(待下一 commit 删)
    └── +test_db_quality_schema.py (6 个)

#2  refactor(db): 删旧 db.py,改 import 路径,verify 1082+6=1088 通过
    ├── 删 nexus/backend/db.py
    ├── 改全仓 import: nexus.backend.db.X → nexus.backend.db (顶层 re-export)
    └── pytest 全量

#3  feat(ws-auth): query fallback 默认关,加 test_ws_auth_query_off.py
    ├── 改 api/ws/auth.py
    └── +test_ws_auth_query_off.py (3 个)

#4  feat(ws): 抽 streaming.py 的 HITL 状态机到 streaming_hitl.py
    ├── 新增 api/ws/streaming_hitl.py
    ├── 改 api/ws/streaming.py (瘦身后 ~700 行)
    └── +test_streaming_hitl.py (6 个)

#5  feat(app-state): 引入 AppState frozen dataclass,改 main.py lifespan
    ├── 新增 app_state.py
    ├── 改 main.py (851 → ~780)
    └── +test_app_state.py (4 个)

#6  feat(fact-check): 统一入口 + 加权算法
    ├── 新增 fact_check/__init__.py
    ├── 改 fact_check/verifiers.py + agents/middleware/fact_check.py
    └── +test_fact_check_weighted.py (5 个)

#7  chore(compliance): wrapper.py 加返回类型 + launcher.py print → logger
    ├── 改 llm/wrapper.py
    ├── 改 launcher.py
    └── pytest 全量 1106 passed
```

### 5.3 提交门禁

- **不破既有**:每 commit 后 `pytest tests/ -q` 必须 ≥ 前 commit 总数
- **不破类型**:每 commit 后 `ruff check` 0 error
- **不破格式**:每 commit 后 `ruff format --check` 0 diff
- **不破行数**:重构后单文件 ≤ 800 行,单函数 ≤ 80 行
- **不破硬约束**:不输出 token / 不绕过 `models_config.save_models()` / 不绕过 `QualityGateMiddleware`

### 5.4 回滚策略

- 每个 commit 独立可回滚(`git revert <sha>`)
- 不强推 `git push --force`
- 出 P0 红测试 → 立即 revert + 重新设计(不修测试)

### 5.5 Definition of Done

- [ ] 1106 passed / 12 skipped / 0 failed
- [ ] ruff check 0 error
- [ ] ruff format 0 diff
- [ ] 5 个新文件存在 + 5 个新测试文件 + 5 个新测试文件覆盖 24 case
- [ ] 旧 `db.py` 删除,所有 import 走 `nexus.backend.db` package
- [ ] `AppState` 不可变,frozen 性质由 test 锁定
- [ ] `fact_check.verify()` 加权算法有 5 个测试
- [ ] `launcher.py` 无 `print` 残留(除控制台保底 1 行)
- [ ] commit log 7 条 Conventional Commits

### 5.6 跨子项目接口冻结

本轮定下后,sub-project A 的对外 API 冻结,sub-project B-F **不能改**:

- `AppState` 字段集
- `fact_check.verify(claim, *, context) -> VerifyResult` 签名
- `db/__init__.py` 顶层 re-export 列表
- `streaming_hitl.HITLInterrupter` 公开方法签名

### 5.7 同步策略

- **本地完成一次性推** —— sub-project A 内部 7 commit 走本地,完成时一个汇总
- CHANGELOG: **A-F 全部完成后一条**(统一记 sub-projects 完成的合规重构)

---

**子项目 A spec 完成,等用户 review 通过后进入 writing-plans。**
