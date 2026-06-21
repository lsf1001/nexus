# Changelog

Nexus 项目的所有重要变更都记录在此文件。本文件格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
