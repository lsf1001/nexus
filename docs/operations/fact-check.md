# 事实校验管线运维指南

> 适用版本：阶段 3 已合并（fact-check pipeline，21 任务合入）
> 适用范围：FactCheckMiddleware、FACT_CHECK_CONSTRAINT、fact-check DB 列、MCP 工具注册、调优阈值

读完本文档你应该能：

1. 解释三层防御（模型自我校验工具 → system prompt 约束 → middleware fail-closed 兜底）
2. 知道 `fail_strategy="closed"` vs `"open"` 的差别与切换方式
3. 看 `quality_scores` 表的 `fact_check_*` 列判断 pipeline 是否在工作
4. 调优 FACT_CHECK_CONSTRAINT 文案或增删 MCP 工具

---

## 1. 架构概览

三层防御：

```
用户问题 + system prompt（含 FACT_CHECK_CONSTRAINT）
       ↓
deepagents middleware 链
  quality_gate → path_aware_hitl → dynamic_identity_middleware
       ↓ FACT_CHECK_CONSTRAINT 在此层注入
  fact_check (FactCheckMiddleware.wrap_model_call, fail_strategy="closed")
       ↓
  force_tool_mw → 模型输出
       ↓
如果 fact_check 检测到冲突 → 抛 FactCheckError，响应被拒
                       ↓
落库 quality_scores（fact_check_* 列）
```

- **Layer 1 — 工具暴露**：4 个 @tool 暴露给 LLM，鼓励自我校验
- **Layer 2 — 行为约束**：FACT_CHECK_CONSTRAINT 把规则塞进 system prompt
- **Layer 3 — 强制拦截**：FactCheckMiddleware 不依赖 LLM，确定性 verifier

模型即使忽略工具 + 忽略 prompt，Layer 3 也会拦下。

---

## 2. 4 个校验工具

| Tool | 输入 | 返回 | 何时用 |
|------|------|------|--------|
| `today` | （无） | `"2026-07-11"` | 用户问「今天/明天」前先调 |
| `weekday_of` | `"YYYY-MM-DD"` | `"星期六"` | 把日期转中文星期 |
| `next_n_days` | start_date, n | JSON 列表 | 需要接下来几天信息 |
| `verify_claims` | str（LLM 拟发出的回复） | JSON `{ok, claims, conflicts}` | **写完回复后必调** |

工具注册位置：`nexus/backend/fact_check/langchain_tools.py`
MCP 模块位置：`nexus/backend/mcp/date_utils.py` / `nexus/backend/mcp/fact_verify.py`
注册到 agent：`nexus/backend/agent/_agent_builder.py`（FACT_CHECK_TOOLS list）

---

## 3. FactCheckMiddleware 与 fail_strategy

`nexus/backend/agents/middleware/fact_check.py`

```python
mw = FactCheckMiddleware(fail_strategy="closed")  # 默认
```

- `closed` — 冲突抛 `FactCheckError`，消息流断掉
- `open` — 冲突仅 WARNING 日志 + 把 `_fact_check_warnings` 挂在 response 上，继续放行

切换方式：改 `_agent_builder.py` 实例化的 `fail_strategy` 参数，**不要**运行时切换。

### 启用/禁用 claim 类型

`FactCheckPipeline` 默认 enabled = `["date_weekday", "math", "unit", "exchange_rate"]`。

要禁用某类，改构造函数：

```python
FactCheckPipeline(config={"enabled_claim_types": ["date_weekday", "math"]})
```

或在 `_agent_builder.py` 注入配置。

---

## 4. FACT_CHECK_CONSTRAINT 系统提示

中文 prompt 强制 LLM 调工具。位置：`nexus/backend/fact_check/prompt_constraint.py`

注入点：`nexus/backend/middleware/dynamic_identity.py` 的 4 层 sandwich

```
FACT_BLOCK → FACT_CHECK → static_prompt → FINAL_REMINDER
```

编辑 `prompt_constraint.py` 中的 `FACT_CHECK_CONSTRAINT` 即可生效。
修改后跑一次事实工具回归：

```bash
./.venv/bin/pytest tests/test_fact_check_system_prompt.py tests/test_mcp_date_utils.py tests/test_mcp_fact_verify.py -q
```

---

## 5. quality_scores 表的 fact_check_* 列

T11 schema 迁移新增：

```sql
fact_check_claims           JSON    -- 所有提取的声明
fact_check_results          JSON    -- 校验结果（只放 conflicts）
fact_check_status           TEXT    -- 'pass' / 'fail' / 'skipped'
fact_check_latency_ms       INTEGER -- pipeline.check() 耗时
```

`save_quality_score()` 扩展：

```python
save_quality_score(
    session_id="...",
    message_id="...",
    rubric="fact_check",     # ← 与 quality gate 区分
    score=1.0,                # 1.0=pass / 0.0=fail
    verdict="accept",         # accept=pass / reject=fail
    reasoning="...",
    fact_check_claims=[...],
    fact_check_results=[...],
    fact_check_status="pass",
    fact_check_latency_ms=42,
)
```

### 监控查询

```sql
-- 24h 内 fail 比例
SELECT
    COUNT(*) FILTER (WHERE fact_check_status = 'fail') AS fail,
    COUNT(*) FILTER (WHERE fact_check_status = 'pass') AS pass,
    COUNT(*) AS total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE fact_check_status = 'fail') / NULLIF(COUNT(*), 0), 2) AS fail_pct
FROM quality_scores
WHERE rubric = 'fact_check'
  AND created_at > datetime('now', '-24 hours');

-- 平均延迟
SELECT AVG(fact_check_latency_ms) FROM quality_scores WHERE rubric = 'fact_check';

-- 最常见冲突类型
SELECT json_extract(fact_check_results, '$[0].kind') AS kind, COUNT(*)
FROM quality_scores
WHERE rubric = 'fact_check' AND fact_check_status = 'fail'
GROUP BY kind ORDER BY COUNT(*) DESC;
```

报警阈值建议：`fail_pct > 20%` 持续 24h → 检查 LLM 行为或 verifier 灵敏度。

---

## 6. 调优 checklist

| 想调什么 | 在哪里改 | 影响 |
|---------|---------|------|
| 增删 enabled claim type | `fact_check/pipeline.py:DEFAULT_ENABLED` | 所有校验都受影响 |
| 工具暴露给 LLM | `fact_check/langchain_tools.py` | LLM 是否能自助校验 |
| 强制 prompt 文案 | `fact_check/prompt_constraint.py` | LLM 行为约束强度 |
| 严格/宽松 middleware 拦截 | middleware 的 `fail_strategy` 参数 | 平衡稳定性 vs 准确性 |
| 单 verifier 灵敏度 | `fact_check/verifiers.py` | 漏报 ↔ 误报 |

每次改完必须跑：

```bash
./.venv/bin/pytest tests/test_fact_check_*.py tests/test_mcp_*.py -q
./.venv/bin/ruff check
./.venv/bin/python scripts/eval_rubrics.py --samples data/fact_check_eval_samples.jsonl --output data/fact_check_eval_report.json
```

报告 `kappa < 0.4` 即视为退化，回滚。

---

## 7. 故障排查

### 全部 fail 突然飙升（>50%）

- 检查 LLM 模型是否换了/降级了
- 检查 `FACT_CHECK_CONSTRAINT` 是否被改动
- 检查 `_agent_builder.py` 是否仍注册全部 4 个工具

### latency_ms > 200

- exchange_rate 网络慢：检查 cache TTL 是否合理（`fact_check/exchange_rate.py`）
- 暂时禁用：把 `"exchange_rate"` 从 DEFAULT_ENABLED 移除

### fact_check_claims / results 是 NULL

- 中间件没装上：grep `FactCheckMiddleware` in `_agent_builder.py:middleware=[...]`
- DB 没自动迁移：删 `~/.nexus/nexus.db` 重启让 `_create_tables` 跑一次

### 模型无视工具和 prompt 仍发错事实

- Layer 3 必然拦截。如未拦截，说明 `fail_strategy="open"` 被改了 → 检查 `_agent_builder.py`
- 也可能是 verifier 漏报 → 跑 `pytest tests/test_fact_check_regression_2026_07_10.py` 验证

---

## 8. 相关资源

- 计划历史：`docs/superpowers/plans/2026-07-10-fact-check-pipeline.md`（21 任务，文件已清理，决策可追溯 Git 历史）
- 回归测试：`tests/test_fact_check_regression_2026_07_10.py`（锁定 2026-07-10 21:45 原 bug）
- E2E 测试：`tests/test_fact_check_e2e_tomorrow.py`
- 元评估样本：`data/fact_check_eval_samples.jsonl`（5 样本，kappa=0.643）
- `quality.md`：judge prompt 调优与 meta-eval 流程
- 相关代码：
  - `nexus/backend/fact_check/*`（extractors, verifiers, pipeline, units, exchange_rate）
  - `nexus/backend/agents/middleware/fact_check.py`
  - `nexus/backend/middleware/dynamic_identity.py`（FACT_CHECK_CONSTRAINT 注入）
  - `nexus/backend/db.py`（fact_check_* columns）