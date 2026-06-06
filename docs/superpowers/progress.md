# Nexus Phase 1+2 进度交接

> **目的**：上下文爆了（~257k/200k）。下次新开会话从本文件 + git log + 文件系统继续，不依赖历史。

## 当前状态

- **分支**：`feat/agent-reliability-quality`
- **基线测试**：192 passed（基线 153 + 41 新增）
- **Phase 1**：✅ 全部 10 task + 5 cleanup 已合并到 `main`（merge commit `6515bb5`）
- **Phase 2**：🟡 启动中
  - ✅ Task 2.1 Rubric 数据结构（`a0e8dc5`，+20 测试）
  - ✅ Task 2.2 中文 Prompt（`3c1afac`，+8 测试）
  - 🟡 Task 2.3 RubricJudge（**in_progress，未派 subagent**）

## 重要 commit 列表

```
6515bb5 merge: Phase 1 容错 (10 tasks) + 4 项 cleanup
eae4b08 refactor(ws): extract WebSocket handler to api/ws.py
aa2efcf chore(ws): upgrade astream_events to v2 (drop deprecation)
915fadd test(e2e): resilience scenarios + observability
785c2a7 feat(frontend): distinguish retryable vs non-retryable errors
e4ee493 fix(ws): restore thinking tags, token_usage, 16-char chunking
4144d6e feat(ws): resilient streaming with resume support
4d09e80 feat(resilience): add StreamGuard for resumable agent streaming
9c96cfa feat(db): add quality_scores and resume_tokens tables
4b98663 feat(resilience): add HMAC-based resume tokens
5a10f76 fix(agent): make ResilientRunnable a BaseChatModel subclass
553ebf8 refactor(agent): wire resilience into get_llm and subagent policies
c55af3e feat(llm): add resilient LLM wrapper with retry+fallback+timeout
bcd9354 feat(llm): add retry/fallback/timeout policy dataclasses
a4a998a feat(llm): add error taxonomy and classifier
3f0ad98 fix(ws): make context_usage meaningful (NEXUS_CONTEXT_WINDOW, default 32K)
a0e8dc5 feat(rubrics): add rubric and score schemas
3c1afac feat(rubrics): add Chinese rubric prompt templates
```

## 关键设计决定（已落地，勿改）

1. `ResilientRunnable` 继承 `BaseChatModel`（避免 deepagents isinstance 失败）
2. `Webhook callback (_handle_wechat_message)` 留在 `main.py`（被 `channels/wechat.py:571` 外部 import）
3. `_agent` / `_agent_lock` 留在 `main.py`（被 `test_ws_resilience.py:299` mock）
4. AUTH 错误不重试不降级（plan 强制）
5. `asyncio.TimeoutError` 在 `errors.py:classify` 直接归 `LLMErrorKind.TIMEOUT`
6. 错误事件永不抛异常（StreamGuard 兜底）
7. 错误路径不发 `done`（避免客户端误判流完成）
8. `add_message` 入库用剥离 `<thinking>` 后的纯文本
9. `type=stats` 元事件在 `done` 之前发
10. `NEXUS_CONTEXT_WINDOW` 默认 32000（修复前分母 200K 太大）
11. `apply_prompts_to_default_rubrics()` **必须**在 lifespan 启动时调一次（否则 Judge 拿到空 prompt）

## 下次开会的快速继续指南

1. **拉取最新**：`git checkout feat/agent-reliability-quality && git pull`
2. **跑测试基线**：`./.venv/bin/pytest tests/ -q` → 期望 192 passed
3. **读取 plan**：`docs/superpowers/plans/2026-06-05-agent-reliability-and-quality.md` §"四、Phase 2"（Task 2.3 - 2.9）
4. **派 Task 2.3 subagent**（RubricJudge）：
   - 接收 prompt：设计 RubricJudge 类，用独立 LLM（建议 `ResilientRunnable` 包装）并发打分（`asyncio.gather`）
   - 严格 JSON 输出 + 解析失败重试 1 次
   - 必须先调 `apply_prompts_to_default_rubrics()`
   - 8+ 测试覆盖：happy path / 部分失败 / JSON 解析失败重试 / safety 低分 / 并发不互相阻塞
   - commit: `feat(rubrics): add RubricJudge with concurrent multi-rubric evaluation`

## 已知非阻塞问题

1. `.codegraph/` 和 `experiments/` 仍 untracked —— 建议加 `.gitignore`，但**未问过用户**
2. `_ensure_column` 在 `idx_sessions_deleted_at` 之前执行（pre-existing bug，不在 Plan 范围）
3. `apply_prompts_to_default_rubrics()` 当前需要手动调（应在 `lifespan` 中加），但 Task 2.5 集成 QualityPipeline 时才需要

## 项目规约（CLAUDE.md 摘要）

- 单文件 < 800 行、单函数 < 80 行、单行 < 150 字符
- 中文 docstring / 中文注释
- snake_case / PascalCase / SCREAMING_CASE
- bare except 严禁
- 不可变默认参数（用 frozenset / tuple）
- 测试放 `tests/` 项目内，禁止 `/tmp`
- 所有 Python 用 `.venv/bin/python`、`.venv/bin/pytest`
- TypeScript 前端用 `cd frontend && npx tsc -b --noEmit`
- ruff 配置：line-length 120，target py311

## 关键文件路径速查

- Plan：`docs/superpowers/plans/2026-06-05-agent-reliability-and-quality.md`
- LLM 韧性：`nexus/backend/llm/{errors,policies,wrapper}.py`
- 容错/续传：`nexus/backend/resilience/{resume,stream_guard}.py`
- WS handler：`nexus/backend/api/ws.py`（main.py:736 装饰）
- Rubric：`nexus/backend/rubrics/{schemas,prompts}.py`（已写）+ judge.py（待写）
- DB：`nexus/backend/db.py`（含 quality_scores / resume_tokens 表）
- 真实 API Key：env `ANTHROPIC_AUTH_TOKEN`（config.py 走 fallback 链）

## 验证命令速查

```bash
# 后端测试
.venv/bin/pytest tests/ -q

# 前端类型
cd frontend && npx tsc -b --noEmit

# Lint
.venv/bin/ruff check nexus/backend/

# 真环境烟测（使用 env ANTHROPIC_AUTH_TOKEN）
~/.nexus/.venv/bin/python -c "
import warnings; warnings.filterwarnings('ignore')
from fastapi.testclient import TestClient
from nexus.backend.main import app
with TestClient(app) as client, client.websocket_connect('/api/ws?token=nexus-default-token') as ws:
    ws.send_json({'content': 'hi', 'title': 'smoke'})
    for _ in range(50):
        msg = ws.receive_json()
        if msg.get('type') in {'done', 'error'}: break
        print(msg.get('type'), msg.get('content', '')[:80] if msg.get('type') == 'chunk' else '')
"
```

---

**下次新会话：先 cat 这个文件 + git log --oneline -10，然后继续 Task 2.3。**
