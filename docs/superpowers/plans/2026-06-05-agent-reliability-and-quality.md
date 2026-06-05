# Agent 可靠性 + 质量门 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Nexus 的 DeepAgent 调用从"靠运气"变成"工程化可靠"，并接入 Rubric 自评使输出质量可控、产出可喂蒸馏模型的偏好数据。

**Architecture:** 两期交付。

- **Phase 1 (容错)**: 引入 LLM 异常分类 → `get_llm` 加 `with_retry` + 超时 + 多模型 fallback；WebSocket 流式从 `astream` 迁到 `astream_events`，引入 resume token；SubAgent 加 per-node 策略。
- **Phase 2 (Rubrics)**: 加 RubricJudge 节点，评分入 `quality_scores` 表，低分走 repair；工具结果自评；写记忆前先评分；导出 DPO/KTO 数据。

**Tech Stack:** Python 3.11+、FastAPI、DeepAgents（基于 LangGraph）、LangChain OpenAI、SQLite、pytest。**新增依赖**：`tenacity>=8.2`、`langgraph>=0.2`（如未随 deepagents 带入）。

---

## 一、范围与依赖

- 仅后端（`nexus/backend/`）和少量前端类型/UI 调整。
- 数据库 schema 新增 2 张表：`quality_scores`、`resume_tokens`；都通过 `db.py:_ensure_column` / `_ensure_table` 模式兼容老库（参照现有迁移风格）。
- 新增 `tenacity` 依赖（在 `pyproject.toml` dependencies 中加）。
- 不重写现有 `agent.py` 核心结构，只在其外做包装与拦截。

---

## 二、文件结构（新增 / 修改）

### 新增

```
nexus/backend/llm/
  __init__.py
  errors.py          # 异常分类 (RateLimit / Timeout / Auth / BadRequest / Unknown)
  policies.py        # RetryPolicy / FallbackPolicy / TimeoutPolicy (dataclass)
  wrapper.py         # build_resilient_llm() — 包 ChatOpenAI + with_retry + fallback

nexus/backend/resilience/
  __init__.py
  resume.py          # ResumeToken (生成/校验/绑定 session)
  stream_guard.py    # StreamGuard — 包装 astream_events，处理中断+恢复

nexus/backend/rubrics/
  __init__.py
  schemas.py         # Rubric / Score / RubricVerdict (Pydantic)
  prompts.py         # 中文 rubric prompt 模板
  judge.py           # RubricJudge (调用 LLM 打分)
  repair.py          # RepairStrategy (rewrite / reject / accept)
  exporter.py        # 导出 DPO/KTO 偏好数据 (jsonl)

nexus/backend/quality/
  __init__.py
  pipeline.py        # QualityPipeline — 串接 judge + repair
  memory_filter.py   # 写记忆前的 rubric 过滤

tests/
  test_llm_resilience.py
  test_resume_token.py
  test_stream_guard.py
  test_rubric_judge.py
  test_rubric_repair.py
  test_quality_pipeline.py
  test_memory_filter.py
  test_rubric_exporter.py
  test_db_migrations.py   # 新表兼容老库
```

### 修改

```
nexus/backend/agent.py          # get_llm → build_resilient_llm; create_subagents 加 per-node policy
nexus/backend/main.py           # websocket_endpoint 用 StreamGuard + resume; astream → astream_events
nexus/backend/sessions.py       # build_prompt 接受可选 quality_filter
nexus/backend/memory.py         # save_memory 前置 rubric 评分
nexus/backend/db.py             # _ensure_table: quality_scores, resume_tokens
nexus/backend/models.py         # StreamEvent 增加 resume_token / error_code / score 字段
nexus/backend/channels/websocket.py  # 透传 resume_token，支持 resume 帧
frontend/src/types/index.ts     # StreamEvent 新字段类型
frontend/src/components/ChatArea.tsx  # 错误 UI 区分"可重试"和"不可重试"
pyproject.toml                  # + tenacity
```

---

## 三、Phase 1 — LangGraph 容错

### Task 1.1: 异常分类 `errors.py`

**Files:** Create `nexus/backend/llm/errors.py`, Create `tests/test_llm_errors.py`

- [ ] **写失败测试**: `classify(exc)` 把 `openai.RateLimitError`/`APITimeoutError`/`AuthenticationError`/`BadRequestError`/`Exception` 分别映射到 `RateLimitError | TimeoutError | AuthError | BadRequestError | UnknownError`，并标注 `retryable: bool`。

```python
# tests/test_llm_errors.py
from openai import RateLimitError, APITimeoutError, AuthenticationError, BadRequestError
from nexus.backend.llm.errors import classify, RetryableError, NonRetryableError

def test_rate_limit_is_retryable():
    exc = RateLimitError("rate limit", response=Mock(status_code=429), body={})
    err = classify(exc)
    assert err.retryable is True
    assert err.kind == "rate_limit"

def test_auth_is_not_retryable():
    exc = AuthenticationError("invalid key", response=Mock(status_code=401), body={})
    err = classify(exc)
    assert err.retryable is False
    assert err.kind == "auth"
```

- [ ] **运行测试** 期望失败（模块不存在）。
- [ ] **实现** `errors.py`：
  - `class LLMErrorKind(StrEnum): RATE_LIMIT, TIMEOUT, AUTH, BAD_REQUEST, CONTEXT_LENGTH, CONTENT_FILTER, UNKNOWN`
  - `class ClassifiedError(Exception)` 携带 `kind`、`retryable`、`original`（**必须继承 Exception，不能继承 BaseException**——`BaseException` 是为 `KeyboardInterrupt` / `SystemExit` 保留的，业务异常继承它会让 `except Exception` 抓不到）
  - `def classify(exc: BaseException) -> ClassifiedError`
- [ ] **运行测试** 期望通过。
- [ ] **commit**: `feat(llm): add error taxonomy and classifier`

### Task 1.2: 策略 dataclass `policies.py`

**Files:** Create `nexus/backend/llm/policies.py`, Create `tests/test_llm_policies.py`

- [ ] **写失败测试**: `RetryPolicy(max_attempts=3, base_delay=0.1, max_delay=2.0)` 计算第 N 次重试 delay；`FallbackPolicy(chains=[primary, secondary])` 顺序遍历。
- [ ] **实现**：
  - `RetryPolicy`: 指数退避 + 抖动（jitter）；`should_retry(attempt, classified_err) -> bool`
  - `FallbackPolicy`: 列表 + 错误过滤（auth 不触发 fallback，只触发 retry）
  - `TimeoutPolicy`: per-step / per-call / per-stream 三档
- [ ] **commit**: `feat(llm): add retry/fallback/timeout policy dataclasses`

### Task 1.3: 韧性 LLM 包装 `wrapper.py`

**Files:** Create `nexus/backend/llm/wrapper.py`, Create `tests/test_llm_wrapper.py`

- [ ] **写失败测试**:
  - `build_resilient_llm(primary, fallback=None, retry=RetryPolicy())` 返回的 LLM：第 1 次 `RateLimitError` → 重试 → 成功（不抛）
  - 重试用尽 + 有 fallback → 自动切到 fallback
  - `AuthenticationError` 不重试也不 fallback，直接抛 `ClassifiedError(kind=AUTH)`
  - 3 次超时 → 抛 `ClassifiedError(kind=TIMEOUT)`
- [ ] **实现**:
  - 用 `tenacity.Retrying` 配合 `retry_error_callback` 调 `classify`
  - 多模型用 `RunnableWithFallbacks`（langchain-core）
  - 超时用 `asyncio.wait_for` 包裹 `ainvoke` / `astream`
- [ ] **commit**: `feat(llm): add resilient LLM wrapper with retry+fallback+timeout`

### Task 1.4: 接入 `get_llm` 改造 `agent.py`

**Files:** Modify `nexus/backend/agent.py:125-149`, Create `tests/test_agent_resilience.py`

- [ ] **写失败测试**: `get_llm()` 默认返回的对象具备 `with_retry`、`with_fallbacks` 属性（或暴露 `invoke_resilient` / `astream_resilient` 方法）。
- [ ] **改 `get_llm`**: 改为返回 `build_resilient_llm(...)` 包装的对象；保留原签名（向后兼容）；新增可选 `retry: RetryPolicy | None = None`、`fallback: ChatOpenAI | None = None` 参数。
- [ ] **改 `create_subagents`**: 为 `code_writer` 设 `timeout=300, max_retries=0`；为 `researcher` 设 `timeout=120, max_retries=2`（在 system prompt 或 subagent config 里登记，不通过 LLM 参数——因为 subagent 内的工具调用有自己的 timeout）。
- [ ] **commit**: `refactor(agent): wire resilience into get_llm and subagent policies`

### Task 1.5: Resume Token `resume.py`

**Files:** Create `nexus/backend/resilience/resume.py`, Create `tests/test_resume_token.py`

- [ ] **写失败测试**:
  - `make_token(session_id, last_event_id)` → 短 token
  - `verify_token(token, session_id)` 校验绑定 + 未过期（默认 30 分钟）
  - 篡改 → 抛 `InvalidResumeToken`
- [ ] **实现**:
  - token = HMAC-SHA256(secret, f"{session_id}:{last_event_id}:{exp}")
  - 编码 base64url
  - secret 从 CONFIG 取（`NEXUS_RESUME_SECRET`，缺省用 ws_token 兜底）
- [ ] **commit**: `feat(resilience): add HMAC-based resume tokens`

### Task 1.6: DB 迁移 `db.py`

**Files:** Modify `nexus/backend/db.py`, Create `tests/test_db_migrations_quality.py`

- [ ] **写失败测试**: 干净库启动后 `quality_scores`、`resume_tokens` 表存在；老库（只有 sessions/messages/memory/tool_stats/session_stats）启动后这两张表也自动创建（不报错，不删数据）。
- [ ] **加 `_ensure_table`** 调用（参照现有 `_ensure_column` 风格）：

```sql
CREATE TABLE IF NOT EXISTS quality_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  message_id TEXT,
  rubric TEXT NOT NULL,            -- e.g. 'faithfulness'
  score REAL NOT NULL,             -- 0.0 - 1.0
  verdict TEXT NOT NULL,           -- 'accept' | 'repair' | 'reject'
  reasoning TEXT,                  -- rubric LLM 的解释
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_quality_session ON quality_scores(session_id);

CREATE TABLE IF NOT EXISTS resume_tokens (
  token TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  last_event_id INTEGER NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **commit**: `feat(db): add quality_scores and resume_tokens tables`

### Task 1.7: StreamGuard `stream_guard.py`

**Files:** Create `nexus/backend/resilience/stream_guard.py`, Create `tests/test_stream_guard.py`

- [ ] **写失败测试**:
  - 模拟上游 `astream_events` 在第 3 个 chunk 后抛 `RateLimitError` → StreamGuard 捕获并尝试重试 → 第二次成功
  - 重试时已发出的 chunk 计入 `replayed_from_event_id`，新事件从断点继续
  - 重试用尽 → StreamGuard yield 一个 `error` 事件（带 `error_code="rate_limit_exhausted"`），不抛
- [ ] **实现**:
  - 内部维护 `last_event_id` 计数器
  - 每次 yield 在事件 dict 上附加 `event_id: int`
  - 失败 → 重新构造 generator（从 last_event_id+1 继续）
  - 关键：DeepAgents 内部状态不可续传，所以**实际续传语义是"重新调用同一 prompt + 跳过已发 event_id"**——这要求 LLM **支持幂等**或重试时带 resume_token 让 LLM 走 deterministic 路径。Phase 1 暂用"幂等重试"（直接重发整段 prompt，前端按 event_id 去重）。
- [ ] **commit**: `feat(resilience): add StreamGuard for resumable agent streaming`

### Task 1.8: WebSocket 改造 `main.py`

**Files:** Modify `nexus/backend/main.py:441-609`, Create `tests/test_ws_resilience.py`

- [ ] **写失败测试**（用 FastAPI `TestClient` 模拟 WebSocket）:
  - 注入一个会触发 retry 的 mock LLM → WS 收到完整 chunk 序列 + `done`，中间无 `error` 事件
  - 注入不可恢复错误（auth） → WS 收到一条 `error` 事件，`error_code="auth"`
  - 客户端断开重连 + 携带 `resume_token` → 服务端从对应 `last_event_id` 之后继续发
- [ ] **改 `websocket_endpoint`**:
  - 把 `agent.astream(...)` 替换为 `StreamGuard(agent).astream_events(...)`
  - 接收客户端 `resume` 帧（含 token），定位 resume 起点
  - 每次发送 chunk 时附 `event_id`
  - 错误事件带 `error_code` / `retryable` 字段
- [ ] **commit**: `feat(ws): resilient streaming with resume support`

### Task 1.9: 前端错误 UI `ChatArea.tsx`

**Files:** Modify `frontend/src/components/ChatArea.tsx`, Modify `frontend/src/types/index.ts`

- [ ] **改 `StreamEvent` 类型**: 增加 `event_id?: number; error_code?: string; retryable?: boolean; resume_token?: string;`
- [ ] **改 `ChatArea`**: 收到 `error` 事件时：
  - `retryable=true` → 显示"重试中…"+ 自动 retry 按钮
  - `retryable=false` → 显示具体原因（如"API Key 无效"）+ 不可重试样式
- [ ] **commit**: `feat(frontend): distinguish retryable vs non-retryable errors`

### Task 1.10: 端到端联调 + 可观测

**Files:** Create `tests/test_e2e_resilience.py`, Modify `nexus/backend/main.py` (埋点)

- [ ] **写 E2E 测试**:
  - `test_rate_limit_recovery`: mock 上游前 2 次 429，第 3 次 200 → WS 全程不报错
  - `test_fallback_to_secondary_model`: primary 持续 503 → 切到 secondary → 成功
  - `test_resume_after_disconnect`: 客户端收到 5 个 chunk 后断开，重连带 token → 收到第 6 个起
  - `test_auth_error_no_retry`: 401 → 1 次 error 事件，code=auth，无 retry
- [ ] **埋点**: 在 StreamGuard 内累计 `retries_count`、`fallbacks_count` → 通过 WS 元事件发给前端（`type=stats`）
- [ ] **commit**: `test(e2e): resilience scenarios + observability`

**Phase 1 验收**:

- 故意配一个无效 API Key 启动 → 立刻 `error_code=auth`，不刷屏重试
- 故意 mock 上游 429 → 5/5 重试恢复成功
- 故意断开 WS 30s 重连 → 续上继续流

---

## 四、Phase 2 — DeepAgents Rubrics

> **前置条件**: Phase 1 完成且稳定运行 1-2 周。

### Task 2.1: Rubric 数据结构 `schemas.py`

**Files:** Create `nexus/backend/rubrics/schemas.py`, Create `tests/test_rubric_schemas.py`

- [ ] **写失败测试**:

```python
def test_faithfulness_score_range():
    s = FaithfulnessScore(score=0.85, reasoning="...", evidence=["quote1"])
    assert 0.0 <= s.score <= 1.0

def test_verdict_thresholds():
    assert RubricVerdict.from_score(0.95, threshold_accept=0.8) == RubricVerdict.ACCEPT
    assert RubricVerdict.from_score(0.5, threshold_accept=0.8, threshold_repair=0.6) == RubricVerdict.REJECT
```

- [ ] **实现**:
  - `Rubric` (name, weight, prompt, accept_threshold, repair_threshold)
  - `Score` (rubric_name, score, reasoning, evidence)
  - `RubricVerdict` (ACCEPT / REPAIR / REJECT)
  - 内置 4 个 Rubric: `faithfulness`、`relevance`、`safety`、`tool_correctness`
- [ ] **commit**: `feat(rubrics): add rubric and score schemas`

### Task 2.2: 中文 Rubric Prompt `prompts.py`

**Files:** Create `nexus/backend/rubrics/prompts.py`, Create `tests/test_rubric_prompts.py`

- [ ] **写失败测试**: 每个 rubric prompt 包含占位符 `{question}` / `{response}` / `{tool_calls}`；长度 200-500 中文字符。
- [ ] **实现**: 4 个中文 prompt，每个含：
  - 角色定义
  - 评分维度（0/0.25/0.5/0.75/1.0 五档）
  - 输出格式约束（JSON: `{score, reasoning, evidence}`）
  - 至少 1 个正例 + 1 个反例
- [ ] **commit**: `feat(rubrics): add Chinese rubric prompt templates`

### Task 2.3: RubricJudge `judge.py`

**Files:** Create `nexus/backend/rubrics/judge.py`, Create `tests/test_rubric_judge.py`

- [ ] **写失败测试**:
  - 用一个固定的"评分用"LLM（独立 model config，避免和主对话互相污染）
  - 喂入已知答案 → 期望 score 在 ±0.2 误差内
  - 评分 LLM 自身故障 → RubricJudge 抛 `RubricJudgeUnavailable`（不污染主流程）
- [ ] **实现**:
  - `class RubricJudge(llm: ChatOpenAI, rubrics: list[Rubric])`
  - `async def judge(question, response, tool_calls=None) -> list[Score]`
  - 并发调用多个 rubric（用 `asyncio.gather`）
  - 严格 JSON 输出 + 解析失败重试 1 次
- [ ] **commit**: `feat(rubrics): add RubricJudge with concurrent multi-rubric evaluation`

### Task 2.4: Repair 策略 `repair.py`

**Files:** Create `nexus/backend/rubrics/repair.py`, Create `tests/test_rubric_repair.py`

- [ ] **写失败测试**:
  - 全部 ACCEPT → `decide()` 返回 ACCEPT
  - safety < 0.5 → 一票否决，返回 REJECT（不管其他）
  - faithfulness < repair_threshold → 返回 REPAIR
  - 重试 1 次后仍 REJECT → 返回 REJECT
- [ ] **实现**:
  - `class RepairStrategy(safety_veto=True, max_repair_attempts=1)`
  - `decide(scores) -> tuple[RubricVerdict, str]`
  - 触发 repair 时返回 repair prompt（追加到下一轮对话）
- [ ] **commit**: `feat(rubrics): add repair decision strategy`

### Task 2.5: Quality Pipeline `quality/pipeline.py`

**Files:** Create `nexus/backend/quality/pipeline.py`, Create `tests/test_quality_pipeline.py`

- [ ] **写失败测试**:
  - 主 LLM 输出 → RubricJudge → ACCEPT → 直接 `add_message` 入库
  - 主 LLM 输出 → RubricJudge → REPAIR → 调一次主 LLM（带 repair prompt）→ 再判 → 入库
  - REJECT → 不入库，返回用户"这个问题我答得不好"提示
- [ ] **实现**:
  - `class QualityPipeline(judge, repair_strategy, main_llm)`
  - `async def run_with_quality(question, raw_response, tool_calls) -> FinalResponse`
  - 所有评分写入 `quality_scores` 表
- [ ] **整合到 `main.py`**: `websocket_endpoint` 拿到 full_response 后 → `pipeline.run_with_quality(...)` → 再发送 final/done
- [ ] **commit**: `feat(quality): integrate rubric pipeline into WebSocket flow`

### Task 2.6: 工具结果自评

**Files:** Modify `nexus/backend/agent.py`, Create `tests/test_tool_self_eval.py`

- [ ] **写失败测试**:
  - subagent 调 `web_search` 后，把 query + results 喂给 RubricJudge 的 `tool_correctness` rubric
  - score < 0.6 → 强制 subagent 重试一次（带"搜索结果不充分"提示）
  - 仍 < 0.6 → 走 fallback（缩小范围再搜 / 切换到 `wikipedia` 工具）
- [ ] **实现**: 在 subagent 的工具节点后插一个 `tool_evaluator` 节点（DeepAgents 提供 `add_node` 钩子）
- [ ] **commit**: `feat(agent): add tool-result self-evaluation for subagents`

### Task 2.7: 记忆去噪 `memory_filter.py`

**Files:** Create `nexus/backend/quality/memory_filter.py`, Modify `nexus/backend/memory.py`, Create `tests/test_memory_filter.py`

- [ ] **写失败测试**:
  - `save_memory(key, value)` 前先用 RubricJudge 评估 `value` 是否"事实/偏好"而非"幻觉/临时上下文"
  - 评估失败 / score < 0.7 → 拒存 + 记日志
  - 已有的"高 confidence"记忆豁免（用 `is_active=1` 标记）
- [ ] **commit**: `feat(memory): filter memory writes through rubric judge`

### Task 2.8: 偏好数据导出 `rubrics/exporter.py`

**Files:** Create `nexus/backend/rubrics/exporter.py`, Create `tests/test_rubric_exporter.py`

- [ ] **写失败测试**:
  - 构造 N 条 (prompt, accepted_response, rejected_response) 记录
  - 导出为 DPO 格式 jsonl：`{"prompt": ..., "chosen": ..., "rejected": ...}`
  - 导出为 KTO 格式 jsonl：`{"prompt": ..., "completion": ..., "label": true/false}`
  - 默认过滤：rejected 与 accepted 的 score 差 ≥ 0.3
- [ ] **实现**:
  - `class PreferenceExporter`
  - `export_dpo(output_path, min_score_gap=0.3)`
  - `export_kto(output_path, ...)`
  - CLI 子命令：`nexus export preferences --format dpo --output ./data/prefs.jsonl`
- [ ] **commit**: `feat(rubrics): export preference data for DPO/KTO training`

### Task 2.9: Rubric 自身质量离线评估

**Files:** Create `tests/test_rubric_meta_eval.py`, Create `scripts/eval_rubrics.py`

- [ ] **写脚本**: 准备 ~50 条标注样本（人工或上一轮 export 的数据），对每条跑 RubricJudge，计算与人工标注的 Pearson / Cohen's kappa
- [ ] **加入 CI**: kappa < 0.4 报警（rubric 不可信）
- [ ] **commit**: `test(rubrics): add meta-evaluation harness`

**Phase 2 验收**:

- 故意给 LLM 一个诱导幻觉的问题 → REJECT，不入库
- 故意触发 repair 路径 → 看到第二次调用日志
- 跑 100 轮对话，导出 preference jsonl → 至少 30 条 (accepted, rejected) 配对
- Rubric meta-eval kappa > 0.5

---

## 五、跨切关注

### 5.1 配置项

新增环境变量（写入 `nexus/backend/config.py`）：

| 变量                         | 默认        | 说明                   |
| -------------------------- | --------- | -------------------- |
| `NEXUS_LLM_MAX_RETRIES`    | 2         | 默认重试次数               |
| `NEXUS_LLM_TIMEOUT_S`      | 60        | 单次 LLM 调用超时          |
| `NEXUS_LLM_FALLBACK_MODEL` | (空)       | 备用模型名（与 active 同样格式） |
| `NEXUS_RESUME_TOKEN_TTL_S` | 1800      | resume token 有效期     |
| `NEXUS_RUBRIC_ENABLED`     | false     | Phase 2 默认关          |
| `NEXUS_RUBRIC_LLM`         | (复用主 LLM) | 评分专用 LLM，可独立配        |

### 5.2 文档

- 更新 `SPEC.md` 核心模块章节，加 `llm/resilience.py` 和 `rubrics/` 说明
- 新增 `docs/operations/resilience.md`：故障演练手册（如何触发 429 验证重试）
- 新增 `docs/operations/quality.md`：rubric 调优指南

### 5.3 监控

- 增加埋点：`llm.retries.total`、`llm.fallbacks.total`、`llm.timeouts.total`、`rubric.verdict.{accept,repair,reject}`、`quality.latency_ms`
- 通过 WS 元事件 `type=stats` 发给前端（前端可暂不展示，但日志里要看到）

---

## 六、风险与开放问题

| 风险                                      | 缓解                                       |
| --------------------------------------- | ---------------------------------------- |
| StreamGuard "幂等重试" 会让用户重看一遍输出           | 前端按 event_id 去重；UI 标"重连中"过渡态             |
| Rubric 评分 LLM 自身成本                      | 评分用更便宜的小模型；只在 final 之前评一次，不评中间 chunk     |
| 中文 rubric 标注数据不足                        | Phase 2 前两周先累积 export 数据做人评，再调 prompt    |
| SubAgent 工具调用的 timeout 与 LLM timeout 冲突 | 工具超时 > LLM timeout（避免 LLM 还没回完工具就死）      |
| 新表破坏老库迁移                                | `_ensure_table` 模式；E2E 加"老库 schema 启动"测试 |
| 端到端联调时间                                 | Phase 1 先做集成测试（mock LLM），最后做真 E2E        |

**开放问题**（执行前请用户确认）:

- Q1: Phase 1 第一刀只动 `get_llm` 还是同时改 WebSocket？建议**只动 get_llm**，WebSocket 留到第二批。
- Q2: 备用模型从 `models_config` 选还是 env 配？建议 **env 配**（多模型配置是用户操作，不是运维操作）。
- Q3: Rubric 评分 LLM 默认用什么？建议**复用主 LLM**（避免引入新 key），后续可独立配。

---

## 七、Self-Review

**1. Spec coverage**:

- ✅ LangGraph retry/timeout → Tasks 1.1, 1.2, 1.3, 1.4
- ✅ WebSocket resumption → Tasks 1.5, 1.6, 1.7, 1.8
- ✅ SubAgent per-node policy → Task 1.4
- ✅ Rubric quality gate → Tasks 2.1, 2.2, 2.3, 2.5
- ✅ 工具自评 → Task 2.6
- ✅ 记忆去噪 → Task 2.7
- ✅ 偏好数据导出 → Task 2.8
- ✅ Rubric 自身质量 → Task 2.9
- ✅ 可观测 → Task 1.10 + 5.3

**2. Placeholder scan**: 已检查。涉及具体实现处都给了代码骨架（异常分类 SQL、RetryPolicy 接口、Rubric 测试），无 TBD。

**3. Type consistency**:

- `ClassifiedError.kind` 在 1.1 定义，1.3/1.4 复用 → 一致
- `ResumeToken` 在 1.5 定义，1.7/1.8 复用 → 一致
- `RubricVerdict` 在 2.1 定义，2.4/2.5 复用 → 一致
- `StreamEvent` 新字段在 1.8 后端加，1.9 前端加 → 一致

**4. 范围检查**: 计划含两个独立子系统（容错 + Rubrics），按建议拆为两期交付，每期结束都有可用的工作软件。

---

## 八、执行计划

**总任务数**: Phase 1 共 10 个 Task，Phase 2 共 9 个 Task。

**建议节奏**:

- **Week 1**: Phase 1 Task 1.1–1.4（LLM 韧性层，纯后端，独立可测）
- **Week 2**: Phase 1 Task 1.5–1.8（resume + WS 改造，需要联调）
- **Week 3**: Phase 1 Task 1.9–1.10（前端 + E2E）
- **Week 4-5**: 灰度观察、修复 edge case
- **Week 6+**: Phase 2（待 Phase 1 稳定后启动）

**TDD 纪律**: 每个 Task 先写失败测试 → 跑红 → 实现 → 跑绿 → commit。
**虚拟环境**: 所有 `pytest` / `pip install` 走 `.venv/bin/pytest`、`.venv/bin/pip`。
**测试位置**: `tests/` 项目内（参照现有 `test_*.py` 风格）。
**中文 docstring**: 公共函数必须有（按 CLAUDE.md §9）。
**文件大小**: 任何文件超 600 行要主动拆（按 CLAUDE.md §2）。

---

*创建于 2026-06-05，基于项目 SPEC.md v2026-06-02 与代码现状评估。*
