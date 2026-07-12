# 质量门调优指南

> 适用版本：阶段 1+2 已合并（提交 `7ea9cbe`）
> 适用范围：rubric 评分阈值、judge prompt、repair 策略、meta-eval 报警

本文档面向需要在生产环境调整 Nexus 质量门的工程师。读完你应该能：

1. 解释 4 个 rubric 维度各自的判定规则与阈值
2. 知道 judge 失败 / 全维度降级时会发生什么
3. 跑一次 meta-eval 并按 kappa 报警决定是否调 prompt
4. 修改阈值、weight、prompt 后知道回滚到哪里

---

## 1. 架构概览

质量门是一条**三段式 pipeline**：

```
用户问题 → 主 Agent 生成 raw_response
              ↓
       QualityPipeline.run_with_quality
              ├─ RubricJudge.judge()         # 4 维度并发评分
              ├─ RepairStrategy.decide()    # ACCEPT / REPAIR / REJECT 决策
              └─ 主 LLM 重生（仅 REPAIR 路径）
              ↓
       FinalResponse → WS done 事件 → 入库
```

- **Judge** 调 4 次 LLM（4 个 rubric 各一次），并发执行
- **Decision** 是纯函数式判定（不调 LLM）
- **Repair** 只在首次 `REPAIR` 触发，二次仍 `REPAIR` → `REJECT`（`max_repair_attempts=1`）
- **Degradation** Judge 全失败或主 LLM 失败 → 降级 `REJECT`，不抛异常

---

## 2. 4 个 Rubric 维度

| 维度 | 权重 | accept 阈值 | repair 阈值 | 关注点 |
|------|------|------------|------------|--------|
| `faithfulness` | 0.35 | 0.8 | 0.6 | 事实准确性、防幻觉 |
| `relevance` | 0.25 | 0.8 | 0.6 | 是否切题、是否覆盖用户意图 |
| `safety` | 0.30 | 0.9 | 0.7 | 有害内容、隐私、医疗/法律 |
| `tool_correctness` | 0.10 | 0.8 | 0.6 | 工具调用参数与结果是否正确 |

权重合计 = 1.00，定义在 `nexus/backend/rubrics/schemas.py:167-198`。

### 2.1 safety 的特殊处理

safety 比其他维度**阈值更严格**（accept 0.9 vs 0.8），且 `RepairStrategy(safety_veto=True)` 默认会**一票否决**：

- `safety < 0.5` → 直接 `REJECT`，不进入 repair 流程
- 原因：避免 LLM 在"自我修复"时反而生成更危险的内容

如要关闭 safety veto（仅在测试或临时调试时），构造 `RepairStrategy(safety_veto=False)`。

### 2.2 tool_correctness 的特殊处理

`tool_correctness` 在无工具调用时（`tool_calls=None`）会**被跳过**，不计入综合判定。判定逻辑见 `nexus/backend/rubrics/tool_evaluator.py`。

---

## 3. 阈值怎么调

### 3.1 调整判定阈值

打开 `nexus/backend/rubrics/schemas.py` 改 `accept_threshold` / `repair_threshold`：

```python
FAITHFULNESS_RUBRIC: Final[Rubric] = Rubric(
    name="faithfulness",
    weight=0.35,
    prompt="...",
    accept_threshold=0.8,   # ← 调这里
    repair_threshold=0.6,   # ← 和这里
)
```

**约束**（`Rubric.__post_init__` 强制）：

- `0.0 <= repair_threshold <= accept_threshold <= 1.0`
- 改坏会被构造期拦截

**调高阈值** → 更严格 → ACCEPT 变少、REJECT 变多
**调低阈值** → 更宽松 → ACCEPT 变多、REJECT 变少

### 3.2 调整权重

`schemas.py` 里 4 个权重合计必须 = 1.00。改完跑一次 `pytest tests/test_rubric_judge.py -k weight` 验证。

**经验法则**：

- `faithfulness` 是底线，权重不要低于 0.3
- `tool_correctness` 一般场景贡献不大，权重 0.1 即可
- 想更看重安全可以把 `safety` 调到 0.4，把 `relevance` 降到 0.15

### 3.3 调整 repair 次数

`RepairStrategy(max_repair_attempts=1)` 是 plan 强制值。改成 2 或更高会让 pipeline 在首次 REPAIR 后再重生一次，但会显著拉长响应时间，**不建议**。

---

## 4. Prompt 调优流程

rubric 的中文 prompt 在 `nexus/backend/rubrics/prompts.py`，由 `apply_prompts_to_default_rubrics()` 在 judge 启动时注入到 `DEFAULT_RUBRICS`。**改完 prompt 必须跑一次 meta-eval**（见第 5 节）确认 kappa 仍 ≥ 0.4。

### 4.1 调优步骤

1. 改 `prompts.py` 里的 4 个常量之一
2. 跑 `python scripts/eval_rubrics.py --samples data/rubric_eval_samples.jsonl --output data/eval_report.json`
3. 看 report：
   - `cohens_kappa >= 0.4` → prompt 合格
   - `cohens_kappa < 0.4` → prompt 不可信，**回滚 + 重新调**
4. commit 前把新 `eval_report.json` 一起提交，CI 会查这个文件

### 4.2 Prompt 编写规则

- **必须**包含 5 档评分（1.0 / 0.75 / 0.5 / 0.25 / 0.0） + 各自含义
- **必须**有 1 个正例 + 1 个反例（few-shot）
- **必须**约束输出为严格 JSON：`{"score": float, "reasoning": str, "evidence": [str]}`
- 长度建议 200-500 中文字符

### 4.3 常见 prompt 调优方向

- **judge 太宽松**（kappa 偏低，ACCEPT 多）：把"基本准确"那档从 0.75 降到 0.5；反例换成边缘 case
- **judge 太严苛**（REJECT 多）：把"明显错误"那档从 0.25 降到 0.1
- **judge 跑题**：加一段"严格按问题评分"指令
- **judge 答非所问**：加 1-2 个反例

---

## 5. Meta-eval：怎么判断 rubric 是否可信

### 5.1 指标含义

- **Pearson 相关系数**（`-1` 到 `+1`）：judge 分数 vs 人工分数的线性相关度
  - ≥ 0.7：强相关
  - 0.4-0.7：中等相关（可接受）
  - < 0.4：judge 评分和人工评分几乎无关
- **Cohen's kappa**（`-1` 到 `+1`）：judge verdict vs 人工 verdict 的一致性
  - ≥ 0.4：acceptable（**plan 强制报警阈值**）
  - < 0.4：rubric 不可信，必须重写 prompt

定义见 `nexus/backend/rubrics/meta_eval.py:41`：`KAPPA_ALERT_THRESHOLD = 0.4`。

### 5.2 跑一次 meta-eval

```bash
# 1. 准备 10+ 条人工标注样本（jsonl）
#    每行：{"prompt", "response", "expected_score", "expected_verdict", "rubric_name"}
#    建议覆盖 accept / repair / reject 三个 verdict 各 ≥ 3 条

# 2. 跑 judge
.venv/bin/python scripts/eval_rubrics.py \
    --samples data/rubric_eval_samples.jsonl \
    --output data/eval_report.json

# 3. 看退出码
#    0 = kappa >= 0.4 (合格)
#    1 = kappa < 0.4 (不合格，CI 应当 fail)
```

CI 集成：在 `pytest` 之后跑 `scripts/eval_rubrics.py`，exit code 1 时让 workflow fail。

### 5.3 真环境验收示例

`data/eval_report.json` 当前的真环境验收结果（commit `7ea9cbe` 之后）：

```
Pearson 相关系数:    +0.973
Cohen's kappa:      +0.591
报警阈值:           0.4
质量合格:           True
```

12 条人工样本（`data/rubric_eval_samples.jsonl`）覆盖：

- `faithfulness`：5 条（3 ACCEPT + 2 REJECT）
- `relevance`：3 条
- `safety`：2 条
- `tool_correctness`：2 条

### 5.4 样本不够 / 质量差怎么办

| 现象 | 原因 | 修复 |
|------|------|------|
| kappa = 0.0 | 人工标注全部是同一 verdict（无边际） | 增加多类别样本 |
| kappa < 0 | judge 与人工 verdict 全部相反 | 检查 prompt 是否语义反向 |
| Pearson ≈ 0 | 分数几乎无方差 | 样本里加边界 case |
| 每次跑结果差很多 | 样本量太小（< 10） | 扩到 20+ 条 |

---

## 6. 故障排查

### 6.1 全部 verdict 都是 REJECT

**症状**：`quality_scores` 表里 `verdict='reject'` 占绝大多数。

**排查**：

```bash
sqlite3 ~/.nexus/nexus.db \
  "SELECT verdict, COUNT(*) FROM quality_scores GROUP BY verdict"
```

**根因**：

1. **judge LLM 404**：model_name / api_base 与主 Agent 不一致。修法见 §6.4
2. **prompt 太严**：judge 把所有回复都判低分。修法见 §4.3
3. **样本 prompt 本身有问题**：rubric prompt 没说清楚评分标准

### 6.2 message_id 全部为 NULL

**症状**：`SELECT COUNT(*) FROM quality_scores WHERE message_id IS NOT NULL` 返回 0。

**根因**：pipeline 写库时没拿到 `message_id` 参数。

**修复**：检查 `nexus/backend/api/ws.py` 的 WS handler，确认在调 `pipeline.run_with_quality(...)` 之前生成了 `message_id` 并传入（commit `7ea9cbe` 已修复）。

### 6.3 Judge 全失败 → 主流程没崩

这是**正确行为**。`RubricJudge.judge()` 全失败时抛 `RubricJudgeError`，`QualityPipeline` 捕获后降级 `REJECT`，不污染主流程。

**只看日志**：`nexus.backend.rubrics.judge` 的 `WARNING` 级别有详细异常。

### 6.4 Judge 报 404

**症状**：judge 调 LLM 时返回 `404 not_found`。

**根因**：`scripts/eval_rubrics.py` 之前用 `CONFIG["model_name"]` 默认值，与主 Agent 的 `get_active_model()` 不一致。

**修复**（已合）：`scripts/eval_rubrics.py` 第 81-87 行、`nexus/backend/main.py` 都改用 `get_active_model()`，确保 model_name / api_base / api_key 三者一致。

### 6.5 REPAIR 路径几乎不触发

**症状**：`verdict='repair'` 几乎为 0。

**根因**：实际分数要么全 ≥ 0.8（直接 ACCEPT），要么全 < 0.6（直接 REJECT），很少落在 [0.6, 0.8) 区间。

**修复**：

- 调低 `accept_threshold` 到 0.85 或调高 `repair_threshold` 到 0.5
- 或在 judge prompt 里明确"中等质量 = 0.7"的边界

### 6.6 Preference 导出为 0 条

**症状**：`scripts/verify_phase2.py --step 4` 跑出 0 DPO pairs。

**根因**：`load_preference_records()` 之前按 `score` 排序取 top/bottom，但因为同一条 message 有 4 个 rubric 评分，sort 之后 top/bottom 都是同一 message。

**修复**（已合）：`nexus/backend/rubrics/_cli_helpers.py` 改成**先按 message_id 分组**，再对组内 score 求平均，最后在组间排序。修完后 100 轮对话可导出 ≥ 30 条 DPO。

---

## 7. 数据库与监控

### 7.1 quality_scores 表

```sql
CREATE TABLE quality_scores (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL,
    message_id  TEXT,                       -- 关联 assistant 消息
    rubric      TEXT NOT NULL,              -- faithfulness / relevance / ...
    score       REAL NOT NULL,              -- 0.0 - 1.0
    verdict     TEXT NOT NULL,              -- accept / repair / reject
    reasoning   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 常用查询

```sql
-- 7 天内 verdict 分布
SELECT verdict, COUNT(*) AS n
FROM quality_scores
WHERE created_at > datetime('now', '-7 days')
GROUP BY verdict;

-- 每个 rubric 的平均分（看哪个维度系统性偏低）
SELECT rubric, AVG(score) AS avg_score, COUNT(*) AS n
FROM quality_scores
WHERE created_at > datetime('now', '-7 days')
GROUP BY rubric;

-- 找出低分（REJECT）最频繁的 session（看是否某类用户/问题触发）
SELECT session_id, COUNT(*) AS rejects
FROM quality_scores
WHERE verdict = 'reject'
GROUP BY session_id
ORDER BY rejects DESC
LIMIT 10;
```

### 7.3 监控报警建议

- 如果 `verdict='reject'` 比例 > 30%：可能 LLM 整体质量下滑或 prompt 变严
- 如果某个 `rubric` 平均分 < 0.6：可能该维度的 prompt 失效
- 如果 `judge 失败率`（reasoning 含 "fallback"）> 5%：judge LLM 自身有问题

---

## 8. 修改 checklist

调任何参数前，**先确认你知道当前生产值**：

| 参数 | 位置 | 当前值 | 文件行号 |
|------|------|--------|---------|
| `KAPPA_ALERT_THRESHOLD` | `rubrics/meta_eval.py` | 0.4 | :41 |
| `faithfulness` weight / 阈值 | `rubrics/schemas.py` | 0.35 / 0.8 / 0.6 | :167-173 |
| `relevance` weight / 阈值 | `rubrics/schemas.py` | 0.25 / 0.8 / 0.6 | :175-181 |
| `safety` weight / 阈值 | `rubrics/schemas.py` | 0.30 / 0.9 / 0.7 | :183-190 |
| `tool_correctness` weight / 阈值 | `rubrics/schemas.py` | 0.10 / 0.8 / 0.6 | :192-198 |
| `safety_veto` | `RepairStrategy` | True | `rubrics/repair.py` |
| `max_repair_attempts` | `RepairStrategy` | 1 | `rubrics/repair.py` |
| `per_rubric_timeout` | `RubricJudge` | 30.0s | `rubrics/judge.py:83` |
| `max_parse_retries` | `RubricJudge` | 1 | `rubrics/judge.py:83` |

调完一个就跑：

```bash
.venv/bin/pytest tests/ -q                  # 全部单测
.venv/bin/python scripts/eval_rubrics.py \
    --samples data/rubric_eval_samples.jsonl  # meta-eval
```

两份都通过才能 commit。

---

## 9. 相关资源

- 计划文档：`docs/superpowers/plans/`（搜索 "rubric"）
- 进度记录：`docs/superpowers/progress.md`
- 真环境验收脚本：`scripts/verify_phase2.py`
- 人工样本：`data/rubric_eval_samples.jsonl`
- 当前 meta-eval 结果：`data/eval_report.json`
- 相关测试：`tests/test_rubric_judge.py`、`tests/test_rubric_meta_eval.py`、`tests/test_quality_pipeline.py`

---

## 10. 与 fact-check 管线的协作

`quality.md` 关心 LLM-judge 评分（`faithfulness` / `relevance` / `safety` / `tool_correctness`）。
[`fact-check.md`](./fact-check.md) 关心**确定性**事实校验（`date_weekday` / `math` / `unit` / `exchange_rate`）。

两者落同一张 `quality_scores` 表，但 `rubric` 字段不同：

- LLM-judge 入库：`rubric='faithfulness'` 等，`fact_check_status='skipped'`
- 确定性 fact-check 入库：`rubric='fact_check'`，`fact_check_status='pass'/'fail'`

### 协同决策

```
输出到达 → FactCheckMiddleware（确定性，毫秒级，hard veto）
        → 阻断 OR 放行
        → 阻断时仍记录为 rubric='fact_check' score=0
        → LLM-judge 评分是对**通过 fact-check 的回复**做软打分
```

判定规则：

- `fact_check_status='fail'` → verdict=reject，**不进入** LLM-judge 评分（节省成本）
- `fact_check_status='pass'` → 进入 RubricJudge 评分，继续沿用 §2 的阈值
- `fact_check_status='skipped'` → 没有事实声明，跳过 fact-check，直接进 RubricJudge

### 监控

```sql
-- 综合质量（fact-check + LLM-judge）
SELECT
    rubric,
    fact_check_status,
    AVG(score) AS avg_score,
    COUNT(*) AS n
FROM quality_scores
WHERE created_at > datetime('now', '-24 hours')
GROUP BY rubric, fact_check_status
ORDER BY rubric, fact_check_status;
```

报警：当 `rubric='fact_check'` 的 fail 数突然上升，意味着模型开始系统性说错日期/星期/数学/单位 — 通常是 LLM provider 升级或路由变化导致，不要当「judge 太严」调，要去查上游。

## 11. WS 鉴权协议 (2026-07 收紧 + 2026-07-12 ABNF 合规)

### 11.0 协议格式变更历史

- 2026-07 首次落地:`Sec-WebSocket-Protocol: nexus-v1.token=<secret>`
- 2026-07-12 修复 ABNF:旧字符串含 `.` / `=`,都违反 RFC 7230 §3.2.6
  `token` ABNF。Chromium ≥149 严格校验,旧格式在 ChatArea mount 时抛
  SyntaxError,被 ErrorBoundary 接管,前端发送消息路径全面失效。改为:
  ```
  Sec-WebSocket-Protocol: nxv1-<base64url(secret)>
  ```
  整个字符串字面合规(browser + tungstenite + http::HeaderValue 三方
  接受 tchar 字符)。旧前缀完全拒,不会"裸 token 解析"的语义漂移。

### 11.1 token 不再进 URL

旧:`ws://host:30000/api/ws?token=<secret>` — 代理 access log / 浏览器历史 / 错误堆栈都会记下 token。

新:`Sec-WebSocket-Protocol: nxv1-<base64url(secret)>` 子协议头。RFC 6455 协商机制,服务端从 upgrade 头解析,token 不在任何 URL 字段。

### 11.2 双路径兼容

| 路径 | 优先级 | 开关 | 适用 |
|---|---|---|---|
| `Sec-WebSocket-Protocol: nxv1-<b64u>` | 高 | 始终启用 | 生产 |
| `?token=...` query string | 低 | `NEXUS_WS_AUTH_QUERY_FALLBACK` (默认 true) | 旧客户端 / 调试 |

下个 major 版本(`2.0.0`)删除 query fallback。

### 11.3 客户端写法

**浏览器原生:**
```typescript
import { encodeWsTokenSubprotocol } from '@/lib/api';
new WebSocket('ws://host:30000/api/ws', [encodeWsTokenSubprotocol(token)]);
```

或按 `frontend/src/hooks/useWsConnection.ts::encodeWsTokenSubprotocol` 手做:
btoa 编码 → `+` → `-`、`/` → `_`、去 `=` padding,前缀 `nxv1-`。

**Tauri (Rust relay):**
```rust
// ws_relay.rs
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
let subproto_value = format!(
    "nxv1-{}",
    URL_SAFE_NO_PAD.encode(token.as_bytes()),
);
let mut request = (&url).into_client_request()?;
request.headers_mut().insert(
    "Sec-WebSocket-Protocol",
    HeaderValue::from_str(&subproto_value)?,
);
tokio_tungstenite::connect_async(request).await?;
```

### 11.4 配置要求

- 后端 `NEXUS_WS_TOKEN` 必填(空字符串 = 拒绝所有客户端)
- 前端 Vite `VITE_NEXUS_WS_TOKEN` 必填,缺失时 `getWsToken()` 抛 Error
- 打包脚本须把后端 `NEXUS_WS_TOKEN` 注入前端构建期 env

### 11.5 排错

- **握手 close 4001 "未授权"**:token 不匹配 / 服务端 `ws_token` 为空
- **subprotocol 返回空 `''`**:客户端发的 subprotocol 格式错(必须 `nxv1-<b64u>` 前缀)
- **Tauri 模式 `ws token is empty`**:Rust relay 检测到空 token,前端 `getWsToken()` 应已先抛
- **Chromium 抛 `SyntaxError: Failed to construct 'WebSocket': The subprotocol 'X' is invalid`**:X 含 `.` 或 `=`,违反 RFC 7230 token ABNF,改用 `nxv1-<b64u>` 形式(2026-07-12 修复后默认合规)
