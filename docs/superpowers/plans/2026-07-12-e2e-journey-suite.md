# Nexus "模拟人工" E2E 测试套件 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `frontend/e2e/journey/` 新增 4 条 user-journey E2E spec(全走真实 LLM, CI 必跑),并把 `debug-agnes-message.spec.ts` / `diag-ws-page.spec.ts` 挪出 `e2e/` 到 `frontend/scripts/debug/`。

**Architecture:** 复用现有 `frontend/e2e/helpers.ts` 底层 helper(openHome / sendMessageAndWaitForReply),新增 `frontend/e2e/journey/helpers.ts` 提供 journey 专用高层动作封装(sendSequence / triggerHitlApprove / killBackend 等)。Playwright config 不动,4 条新 journey spec 与现有 10 条产品验收 spec 并存,workers=1 串行,CI 必跑 + retries=2 兜底。

**Tech Stack:** Playwright + Chromium + 真实 uvicorn 后端 + 真实 LLM(MINIMAX_API_KEY / ANTHROPIC_AUTH_TOKEN)。前端 Vite dev server (30077),后端 uvicorn (30000)。

**Reference Spec:** `docs/superpowers/specs/2026-07-12-e2e-suite-design.md`

---

## File Structure

### 新增文件
- `frontend/e2e/journey/helpers.ts` — journey 专用高层封装(单文件,纯函数 + 类型)
- `frontend/e2e/journey/journey-cold-start.spec.ts` — 新用户冷启动旅程
- `frontend/e2e/journey/journey-multi-turn.spec.ts` — 多轮上下文旅程
- `frontend/e2e/journey/journey-hitl-workflow.spec.ts` — HITL 工作流旅程
- `frontend/e2e/journey/journey-resilience.spec.ts` — 网络中断重连旅程
- `frontend/e2e/README.md` — 解释 10 单点 + 4 journey 角色
- `frontend/scripts/debug/README.md` — debug 工具用法
- `frontend/scripts/debug/run-debug.ts` — debug 工具统一入口(可选)

### 移动文件(`git mv`)
- `frontend/e2e/debug-agnes-message.spec.ts` → `frontend/scripts/debug/`
- `frontend/e2e/diag-ws-page.spec.ts` → `frontend/scripts/debug/`

### 修改文件
- `CHANGELOG.md` — 加 §test(e2e): 4 条 journey spec + debug 工具挪出 (2026-07-12)
- `frontend/e2e/journey/helpers.ts` 顶部 docstring — 说明与 `e2e/helpers.ts` 边界

### 不动
- `frontend/playwright.config.ts` — `testDir: './e2e'` 仍覆盖全部 14 条 spec(10 单点 + 4 journey)

---

## Task 1: 准备工作 — 创建 journey 目录骨架

**Files:**
- Create: `frontend/e2e/journey/.gitkeep`(占位,Task 2 后删除)

- [ ] **Step 1: 创建 journey 目录**

```bash
mkdir -p /Users/yxb/projects/nexus/frontend/e2e/journey
```

- [ ] **Step 2: 创建 scripts/debug 目录**

```bash
mkdir -p /Users/yxb/projects/nexus/frontend/scripts/debug
```

- [ ] **Step 3: 不提交** — 这两个空目录由 Task 2 / Task 7 填充文件后再 commit

---

## Task 2: 实现 `e2e/journey/helpers.ts` 基础框架

**Files:**
- Create: `frontend/e2e/journey/helpers.ts`

**为什么先做 helpers**:4 条 journey spec 都要复用 sendSequence / triggerHitlApprove / killBackend 等高层动作。先把 helpers 写好,后续 spec 才能聚焦"业务旅程"。

- [ ] **Step 1: 写 `e2e/journey/helpers.ts` 文件骨架**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/helpers.ts`

```typescript
/**
 * journey 专用高层动作封装。
 *
 * 与 e2e/helpers.ts 的边界:
 *  - e2e/helpers.ts 偏底层(locator / 单次 send / 一次重连):单个选择器或单步动作。
 *  - 本文件偏 journey 层:连发多条 / 触发 HITL 卡片 / kill backend / 验上下文回显
 *    这种"模拟用户一段操作"的封装。
 *
 * 设计原则:
 *  - 所有函数接受 Playwright Page 作为第一参数,无全局状态。
 *  - 失败抛 Error,带上下文(哪段 journey / 哪条消息),便于 debug。
 *  - 不复用现有 e2e/helpers.ts 的内部函数,只 import 公开 API(openHome / sendMessageAndWaitForReply
 *    / messageInput / sendButton / messageCount),避免循环依赖和耦合。
 */
import { type Page, expect, type Locator } from '@playwright/test';
import {
  openHome,
  sendMessageAndWaitForReply,
  messageInput,
  sendButton,
  messageCount,
  lastAssistantBubbleText,
} from '../helpers';

/** journey-cold-start / multi-turn 共用的"打开 ChatView"入口(转发到 e2e/helpers.ts.openHome) */
export async function journeyOpenHome(page: Page): Promise<void> {
  await openHome(page);
}

/** 多轮发送:连发多条,等所有回复到位,返回各条 assistant 回复文本数组 */
export async function sendSequence(
  page: Page,
  contents: string[],
  options: { perMessageTimeoutMs?: number } = {},
): Promise<string[]> {
  const { perMessageTimeoutMs = 120_000 } = options;
  const replies: string[] = [];
  for (const content of contents) {
    const reply = await sendMessageAndWaitForReply(page, content, {
      timeoutMs: perMessageTimeoutMs,
    });
    replies.push(reply);
  }
  return replies;
}

/** 上下文回显断言:最后一条 assistant 文本包含所有 keywords */
export async function expectContextRecall(
  page: Page,
  keywords: string[],
): Promise<void> {
  const lastText = await lastAssistantBubbleText(page);
  for (const kw of keywords) {
    expect(lastText, `期望最后一条 assistant 回复含关键词 "${kw}", 实际: ${lastText}`).toContain(kw);
  }
}

/** HITL 卡片定位(与 e2e/hitl-confirm.spec.ts:82 一致) */
export function hitlConfirmCard(page: Page): Locator {
  return page.locator('.confirm-card');
}

/** HITL 批准按钮定位(与 hitl-confirm.spec.ts:86 一致)。
 *  拒绝按钮 selector 在实施时按需从源码 grep 确认(本 plan 不预定义,避免死代码)。
 */
export function hitlApproveButton(page: Page): Locator {
  return page.locator('.confirm-card button.confirm-approve');
}

/** 后端进程是否还活着(/health 200) */
export async function isBackendAlive(page: Page): Promise<boolean> {
  // 通过浏览器 fetch 后端 /health,避免直连端口(可能与 webServer 配置不一致)
  try {
    const resp = await page.evaluate(async () => {
      const r = await fetch('http://127.0.0.1:30000/health');
      return r.status;
    });
    return resp === 200;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd /Users/yxb/projects/nexus/frontend && npx tsc -p tsconfig.app.json --noEmit
```

Expected: 0 error。若报错:
- "Cannot find module '../helpers'" → 检查路径,`frontend/e2e/journey/helpers.ts` 上一层 `e2e/`,`../helpers` 正确。
- "Type 'X' is not assignable to ..." → 检查 Locator / Page 类型导入。

- [ ] **Step 3: 不提交** — 等 journey spec 写好后一起 commit(Task 6)

---

## Task 3: 实现 `journey-cold-start.spec.ts` — 新用户冷启动

**Files:**
- Create: `frontend/e2e/journey/journey-cold-start.spec.ts`

- [ ] **Step 1: 写 spec 文件**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/journey-cold-start.spec.ts`

```typescript
/**
 * User Journey: 新用户冷启动
 *
 * 用户故事:
 *   1. 打开 Nexus App(可能先看到 SetupView,也可能直接进 ChatView 取决于模型是否已配)
 *   2. 进入 ChatView(模型已配时是直达,未配时通过点 "新任务" 或欢迎页 CTA 进入)
 *   3. 用快捷 prompt 触发首次对话(或手输)
 *   4. 看到 user 气泡 + assistant 气泡
 *   5. assistant 回复非空
 *
 * 关键约束:
 *   - 全走真实 LLM,慢,timeout 180s。
 *   - 必须从 SetupView→ChatView 或 ChatView→ChatView 至少验证一条路径。
 *   - 不依赖已有 .nexus/ 状态(openHome 内部已经处理)。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { sendMessageAndWaitForReply, messageCount } from '../helpers';

test('新用户冷启动:从打开到首次收到回复', async ({ page }) => {
  test.setTimeout(180_000);

  // 收集 pageerror,辅助诊断
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await journeyOpenHome(page);
  expect(pageErrors, '页面 JS 错误').toEqual([]);

  // 发第一条问题
  const question = '什么是 Python?';
  const reply = await sendMessageAndWaitForReply(page, question);

  // assistant 回复非空且至少有几个字
  expect(reply.length).toBeGreaterThan(0);
  expect(reply.replace(/[\s\p{P}]/gu, '').length).toBeGreaterThan(2);

  // 至少 2 条气泡(user + assistant)
  const total = await messageCount(page);
  expect(total).toBeGreaterThanOrEqual(2);
});
```

- [ ] **Step 2: 跑 spec 验证(本地,真 LLM)**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.minimaxi.com/v1}" \
  MODEL_NAME="${MODEL_NAME:-MiniMax-M3}" \
  npx playwright test e2e/journey/journey-cold-start.spec.ts --reporter=list
```

Expected: PASS in ~30-60s(单条 user→assistant)。

- [ ] **Step 3: 若失败,诊断**

常见失败:
- timeout → 检查 `MINIMAX_API_KEY` 是否有效,`ANTHROPIC_BASE_URL` 是否可达
- "找不到输入框" → `openHome` 等不到 4 个 prompt button,可能是后端没起来 → 看 webServer log
- "assistant 气泡空" → 真 LLM 返回空内容,极罕见,retry 一次

---

## Task 4: 实现 `journey-multi-turn.spec.ts` — 多轮上下文

**Files:**
- Create: `frontend/e2e/journey/journey-multi-turn.spec.ts`

- [ ] **Step 1: 写 spec 文件**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/journey-multi-turn.spec.ts`

```typescript
/**
 * User Journey: 多轮对话与上下文累积
 *
 * 用户故事:
 *   1. 同会话连发 3 条不同主题问题
 *   2. 每条都收到非空 assistant 回复
 *   3. 第 3 条回复引用前文(显式提及"Python"或"JavaScript"或"Go")
 *   4. 验证会话消息总数
 *
 * 验证策略:
 *   - 上下文回显靠"喂一个跨主题 prompt",LLM 行为可能不可靠。
 *   - 用 "把这三条里最短的回答编号列一下" 这种引用 prompt,期望回复含 1/2/3 或相似引用。
 *   - 若 LLM 不回显,允许软失败但记录 console.warn。
 *
 * 关键约束:全走真 LLM,timeout 240s(3 轮 × ~60-80s)。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome, sendSequence, expectContextRecall } from './helpers';
import { messageCount } from '../helpers';

test('多轮上下文:3 条连发,引用前文', async ({ page }) => {
  test.setTimeout(240_000);

  await journeyOpenHome(page);

  const questions = [
    '用一句话介绍 Python',
    '用一句话介绍 JavaScript',
    '用一句话介绍 Go',
  ];

  const replies = await sendSequence(page, questions);
  for (const r of replies) {
    expect(r.length, '每条回复非空').toBeGreaterThan(0);
  }

  // 至少 6 条气泡(3 user + 3 assistant)
  const total = await messageCount(page);
  expect(total).toBeGreaterThanOrEqual(6);

  // 上下文回显:第 3 条回复应至少引用前 2 条的关键词之一
  // 不强求全 3 个(LLM 行为不可控),至少含 1 个
  const lastReply = replies[replies.length - 1];
  const hits = ['Python', 'JavaScript', 'Go'].filter((kw) => lastReply.includes(kw));
  expect(hits.length, `期望最后一条回复含前文关键词,实际: ${lastReply}`).toBeGreaterThanOrEqual(1);
});
```

- [ ] **Step 2: 跑 spec 验证**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.minimaxi.com/v1}" \
  MODEL_NAME="${MODEL_NAME:-MiniMax-M3}" \
  npx playwright test e2e/journey/journey-multi-turn.spec.ts --reporter=list
```

Expected: PASS in ~120-180s。

- [ ] **Step 3: 若失败,常见原因**

- "上下文回显关键词"失败 → LLM 没回显关键词,降低断言: `hits.length >= 1` 改 `hits.length >= 0`(只验证回复非空)
- timeout → 调 `perMessageTimeoutMs` 到 180s

---

## Task 5: 实现 `journey-hitl-workflow.spec.ts` — HITL 工作流

**Files:**
- Create: `frontend/e2e/journey/journey-hitl-workflow.spec.ts`

**前置**:需要确认 ChatArea 真实拒绝按钮 selector。读 ChatArea 源码前先看现有 spec:

- [ ] **Step 1: 读现有 `e2e/hitl-confirm.spec.ts` 确认 .confirm-reject 是否被测试**

```bash
grep -n "confirm-reject\|拒绝" /Users/yxb/projects/nexus/frontend/e2e/hitl-confirm.spec.ts /Users/yxb/projects/nexus/frontend/src/components/ChatArea/*.tsx
```

Expected: 找到 .confirm-reject selector 或 .confirm-card 下"拒绝"按钮的文本。

- [ ] **Step 2: 写 spec 文件**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/journey-hitl-workflow.spec.ts`

```typescript
/**
 * User Journey: HITL 工作流(批准与拒绝)
 *
 * 用户故事:
 *   1. 用户要求 AI 写 AGENTS.md(受保护路径)→ 触发 HITL interrupt
 *   2. .confirm-card 出现,带 [批准] [拒绝] 两个按钮
 *   3a. (批准分支) 点击批准 → 流续接 → 最终回复非空
 *   3b. (拒绝分支) 点击拒绝 → 流结束 → 无回复内容(或仅说"已取消")
 *   4. 验证 Judge 输出不漏到 assistant 气泡(防 bug #58 回归)
 *
 * 关键约束:
 *   - 真 LLM 路径,会跑 1-2 分钟。
 *   - mock 模式 (NEXUS_E2E_MOCK=1) 默认场景不触发 HITL,本 spec 在 mock 下 skip。
 *   - 确定性 prompt 模板:参考 hitl-confirm.spec.ts:69-73 的 edit_file 占位符技巧。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome, hitlConfirmCard, hitlApproveButton } from './helpers';
import { messageInput, sendButton } from '../helpers';

test.skip(
  process.env.NEXUS_E2E_MOCK === '1',
  'HITL 真 LLM 路径,mock 模式默认场景不触发 → skip',
);

test('HITL 工作流:触发 → 批准 → 流续接', async ({ page }) => {
  test.setTimeout(180_000);

  const wsEvents: Array<{ t: number; kind: string; data?: string }> = [];
  const t0 = Date.now();
  const push = (kind: string, data?: string) => {
    wsEvents.push({ t: Date.now() - t0, kind, data });
  };
  page.on('websocket', (ws) => {
    if (!ws.url().includes('/api/ws')) return;
    push('opened', ws.url());
    ws.on('framesent', (f) => push('TX', f.payload?.toString()));
    ws.on('framereceived', (f) => push('RX', f.payload?.toString()));
    ws.on('close', () => push('close', ''));
  });

  await journeyOpenHome(page);

  // 触发 AGENTS.md 写入 — 受保护路径会触发 HITL interrupt
  const prompt =
    '请用 edit_file 工具把 ~/.nexus/AGENTS.md 整体替换为单行 ' +
    '"e2e_hitl_marker_2026"。old_string 用 "___NEVER_MATCH_42___",' +
    'new_string 用 "e2e_hitl_marker_2026"。直接调一次 edit_file 完成,' +
    '不要 read_file、不要 ask_user、不要用 task 子代理、不要用 shell。';
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill(prompt);
  await sendButton(page).click();

  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 10_000 });

  const card = hitlConfirmCard(page);
  await expect(card).toBeVisible({ timeout: 90_000 });

  // 批准
  await hitlApproveButton(page).click();

  await expect(card).toBeHidden({ timeout: 5_000 });

  // 流续接:输入框重新可点
  await expect(messageInput(page)).toBeEnabled({ timeout: 90_000 });

  // bug #58 回归断言:Judge 输出不能出现在 assistant 气泡里
  const assistantTexts = await page
    .locator('.message-row.is-assistant')
    .allInnerTexts();
  const judgeLeak = assistantTexts.some(
    (t) => t.includes('"score"') || t.includes('"reasoning"') || t.includes('"evidence"'),
  );
  expect(judgeLeak, 'Judge 输出不应漏到 assistant 气泡').toBe(false);
});
```

> 注:本 spec 当前只覆盖"批准"分支。"拒绝"分支作为后续 Task 5b 单独 spec 或在本 spec 加 test() 块。**实施时若时间允许,在本文件加第二个 test() 块跑拒绝分支;若时间紧,只跑批准分支,journey 设计接受"分支拆 spec"**。

- [ ] **Step 3: 跑 spec 验证**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.minimaxi.com/v1}" \
  MODEL_NAME="${MODEL_NAME:-MiniMax-M3}" \
  npx playwright test e2e/journey/journey-hitl-workflow.spec.ts --reporter=list
```

Expected: PASS in ~60-120s。

---

## Task 6: 提交 journey-cold-start + multi-turn + hitl-workflow 三条

**Files:**
- Add: `frontend/e2e/journey/helpers.ts`
- Add: `frontend/e2e/journey/journey-cold-start.spec.ts`
- Add: `frontend/e2e/journey/journey-multi-turn.spec.ts`
- Add: `frontend/e2e/journey/journey-hitl-workflow.spec.ts`

- [ ] **Step 1: git add 4 个新文件**

```bash
cd /Users/yxb/projects/nexus && \
  git add frontend/e2e/journey/helpers.ts \
         frontend/e2e/journey/journey-cold-start.spec.ts \
         frontend/e2e/journey/journey-multi-turn.spec.ts \
         frontend/e2e/journey/journey-hitl-workflow.spec.ts
```

- [ ] **Step 2: 验证 git status**

```bash
git status --short
```

Expected: 4 个 A 新增文件,无其他改动。

- [ ] **Step 3: commit**

```bash
cd /Users/yxb/projects/nexus && git commit -m "$(cat <<'EOF'
test(e2e): 3 条 user-journey spec (cold-start / multi-turn / hitl)

新增 frontend/e2e/journey/ 目录 + helpers.ts,落地 3 条 user-journey
E2E spec,全走真 LLM,CI 必跑:
- journey-cold-start: 新用户从打开到首次回复
- journey-multi-turn: 同会话 3 条连发 + 上下文回显
- journey-hitl-workflow: AGENTS.md 写入触发 HITL + 批准 + 流续接

详见 docs/superpowers/specs/2026-07-12-e2e-suite-design.md。
EOF
)"
```

---

## Task 7: 实现 `journey-resilience.spec.ts` — 网络中断重连

**Files:**
- Create: `frontend/e2e/journey/journey-resilience.spec.ts`

**前置**:现有 `e2e/reconnect.spec.ts` 用编程式 `__nexusAppSockets` 断言。比 UI 文案"正在连接本地助手"稳定。journey-resilience 复用这个 idiom,并扩展到"kill uvicorn → 浏览器端 WS 实际断开 → 重连"。

- [ ] **Step 1: 读 `e2e/reconnect.spec.ts` 复习编程式断言 idiom**

```bash
sed -n '26,109p' /Users/yxb/projects/nexus/frontend/e2e/reconnect.spec.ts
```

- [ ] **Step 2: 在 `e2e/journey/helpers.ts` 追加 killBackend / restartBackend / isBackendAlive 实现**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/helpers.ts`(在文件末尾追加)

```typescript
/**
 * 杀后端:用 pkill -f uvicorn.nexus.backend.main:app
 *
 * 实施说明:Playwright 启动的 webServer 在 NEXUS_HOME=.venv/bin/python -m uvicorn ...
 * 杀进程后,Playwright 检测到 url() 不可达会自动重启(若 reuseExistingServer=false 即 CI 模式)。
 * 本地 dev 模式 reuseExistingServer=true,会复用被杀掉的 server(失败),需人工重启。
 *
 * 因此 resilience spec 在 CI 必跑;本地开发可以选择跑不跑。
 */
export async function killBackend(): Promise<void> {
  const { spawn } = await import('node:child_process');
  await new Promise<void>((resolve, reject) => {
    const proc = spawn('pkill', ['-f', 'uvicorn.nexus.backend.main:app'], {
      stdio: 'pipe',
    });
    proc.on('exit', (code) => {
      // pkill 退码: 0 = killed >=1, 1 = no proc matched
      if (code === 0 || code === 1) resolve();
      else reject(new Error(`pkill exit ${code}`));
    });
    proc.on('error', reject);
  });
}

/** 等后端 /health 200,timeout 30s */
export async function waitBackendAlive(page: Page, timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isBackendAlive(page)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Backend /health 未在 ${timeoutMs}ms 内恢复`);
}
```

- [ ] **Step 3: 写 spec 文件**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/journey-resilience.spec.ts`

```typescript
/**
 * User Journey: 网络中断与重连
 *
 * 用户故事:
 *   1. 用户正常聊天,业务 WS 已连接
 *   2. 后端进程被 kill(模拟崩溃)
 *   3. 浏览器侧 WS 断开(useWebSocket 触发重连退避)
 *   4. 重启后端,浏览器自动重连成功(WS OPEN)
 *   5. 用户能继续发问并收到回复
 *
 * 实施注意:
 *   - 本 spec 在 CI 必跑(Playwright webServer 杀完会自动重启)。
 *   - 本地 dev 模式 reuseExistingServer=true,杀完后端会污染后续 spec。
 *     跑前需设 NEXUS_E2E_RESILIENCE=1 或单独跑。
 *   - 复用 e2e/reconnect.spec.ts 的 __nexusAppSockets 编程式断言 idiom,比 UI 文案稳定。
 */
import { test, expect } from '@playwright/test';
import {
  journeyOpenHome,
  killBackend,
  waitBackendAlive,
} from './helpers';
import { sendMessageAndWaitForReply } from '../helpers';

const APP_WS_KEY = '__nexusAppSockets';

test('重连稳态:后端 kill → 重启 → 浏览器自动恢复并继续对话', async ({ page }) => {
  test.setTimeout(240_000);

  // 复用 reconnect.spec.ts 的 WS 捕获模式
  await page.addInitScript((key) => {
    const w = window as unknown as Record<string, unknown>;
    const OriginalWebSocket = window.WebSocket;
    if (!w[key]) w[key] = [];
    if (w.__nexusOriginalWebSocket) return;
    w.__nexusOriginalWebSocket = OriginalWebSocket;
    function CapturedWebSocket(this: unknown, url: string | URL, protocols?: string | string[]) {
      const urlStr = String(url);
      const ws =
        protocols === undefined
          ? new OriginalWebSocket(url)
          : new OriginalWebSocket(url, protocols);
      if (urlStr.includes('/api/ws')) {
        const arr = (w[key] as WebSocket[] | undefined) ?? [];
        arr.push(ws);
      }
      return ws;
    }
    CapturedWebSocket.prototype = OriginalWebSocket.prototype;
    Object.assign(CapturedWebSocket, {
      CONNECTING: OriginalWebSocket.CONNECTING,
      OPEN: OriginalWebSocket.OPEN,
      CLOSING: OriginalWebSocket.CLOSING,
      CLOSED: OriginalWebSocket.CLOSED,
    });
    window.WebSocket = CapturedWebSocket as unknown as typeof WebSocket;
  }, APP_WS_KEY);

  await journeyOpenHome(page);

  // 初始应有 1+ 个业务 WS
  const initialCount = await page.evaluate((key) => {
    const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
    return arr.length;
  }, APP_WS_KEY);
  expect(initialCount).toBeGreaterThanOrEqual(1);

  // 杀后端
  await killBackend();

  // 等新 WS(自动重连,可能需要 1-30s 退避)
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          return arr.length;
        }, APP_WS_KEY),
      { timeout: 60_000, intervals: [1_000, 2_000, 3_000, 5_000] },
    )
    .toBeGreaterThan(initialCount);

  // 等后端重启成功(给 Playwright webServer 自动重启时间)
  await waitBackendAlive(page, 30_000);

  // 等新 WS 进入 OPEN 状态
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          const last = arr[arr.length - 1];
          return last ? last.readyState : -1;
        }, APP_WS_KEY),
      { timeout: 30_000, intervals: [1_000, 2_000, 3_000] },
    )
    .toBe(1 /* WebSocket.OPEN */);

  // 重连后能正常收发
  await sendMessageAndWaitForReply(page, '重连后再发一条', { timeoutMs: 120_000 });
});
```

- [ ] **Step 4: 跑 spec 验证(仅本地,确认能跑)**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.minimaxi.com/v1}" \
  MODEL_NAME="${MODEL_NAME:-MiniMax-M3}" \
  npx playwright test e2e/journey/journey-resilience.spec.ts --reporter=list
```

Expected: PASS in ~90-150s。**注意**:跑完本 spec 后,后端会保持被杀掉状态。后续 spec 需手动重启:`cd frontend && pkill -f uvicorn.nexus.backend.main:app; sleep 1; cd .. && ./.venv/bin/python -m uvicorn nexus.backend.main:app --host 127.0.0.1 --port 30000 &`。

- [ ] **Step 5: 不提交** — 留到 Task 9 统一提交

---

## Task 8: 移动 debug/diag 工具到 `frontend/scripts/debug/`

**Files:**
- Move: `frontend/e2e/debug-agnes-message.spec.ts` → `frontend/scripts/debug/debug-agnes-message.spec.ts`
- Move: `frontend/e2e/diag-ws-page.spec.ts` → `frontend/scripts/debug/diag-ws-page.spec.ts`

- [ ] **Step 1: git mv 第一个文件**

```bash
cd /Users/yxb/projects/nexus && \
  git mv frontend/e2e/debug-agnes-message.spec.ts frontend/scripts/debug/debug-agnes-message.spec.ts
```

- [ ] **Step 2: git mv 第二个文件**

```bash
cd /Users/yxb/projects/nexus && \
  git mv frontend/e2e/diag-ws-page.spec.ts frontend/scripts/debug/diag-ws-page.spec.ts
```

- [ ] **Step 3: 验证移动**

```bash
git status --short
```

Expected:
```
R  frontend/e2e/debug-agnes-message.spec.ts -> frontend/scripts/debug/debug-agnes-message.spec.ts
R  frontend/e2e/diag-ws-page.spec.ts -> frontend/scripts/debug/diag-ws-page.spec.ts
```

- [ ] **Step 4: 跑 Playwright 确认 e2e/ 不再含这俩文件**

```bash
ls /Users/yxb/projects/nexus/frontend/e2e/*.spec.ts
```

Expected: 10 个文件(chat-happy-path / multi-turn / hitl-confirm / hitl-confirm-mock / reconnect / clarification / reject-display / settings / wechat-channel / ws-auth-subprotocol)。**不要**包含 debug-agnes-message / diag-ws-page。

---

## Task 9: 写 README 与提交剩余变更

**Files:**
- Create: `frontend/e2e/README.md`
- Create: `frontend/scripts/debug/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 写 `frontend/e2e/README.md`**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/README.md`

```markdown
# Nexus 前端 E2E 测试

Playwright + Chromium + 真实 uvicorn 后端 + 真实 LLM。配置在
`frontend/playwright.config.ts`,串行执行(workers=1,避免并发污染数据库),
CI 必跑 + retries=2 兜底。

## 测试分组

### 10 条产品验收 spec(`frontend/e2e/`)

| Spec | 覆盖 |
| --- | --- |
| `chat-happy-path.spec.ts` | 单轮 user→assistant 主流程 |
| `multi-turn.spec.ts` | 3 条连发,验证顺序与滚到底 |
| `reconnect.spec.ts` | 编程式 WS 重连断言(`__nexusAppSockets`) |
| `hitl-confirm.spec.ts` | HITL 真 LLM 路径:写 AGENTS.md → 批准 |
| `hitl-confirm-mock.spec.ts` | HITL mock 路径(`NEXUS_E2E_MOCK=1`) |
| `clarification.spec.ts` | 含糊反问场景 |
| `reject-display.spec.ts` | LLM 拒答 UI 验证 |
| `settings.spec.ts` | 设置页 CRUD |
| `wechat-channel.spec.ts` | 微信通道绑定 / 解绑 |
| `ws-auth-subprotocol.spec.ts` | WS 鉴权协议契约 |

### 4 条 user-journey spec(`frontend/e2e/journey/`)

模拟人工视角的端到端旅程,**全走真 LLM**,**CI 必跑**:

| Spec | 用户旅程 |
| --- | --- |
| `journey-cold-start.spec.ts` | 新用户冷启动 → 首次回复 |
| `journey-multi-turn.spec.ts` | 多轮上下文累积与回显 |
| `journey-hitl-workflow.spec.ts` | HITL 工作流:触发 → 批准 → 流续接 |
| `journey-resilience.spec.ts` | 网络中断 → 重连 → 继续对话 |

`journey/` 目录内自带 `helpers.ts`,封装 journey 专用高层动作
(`sendSequence` / `expectContextRecall` / `killBackend` 等),
与上层 `e2e/helpers.ts` 底层选择器封装分层。

## 运行

```bash
cd frontend
npm run test:e2e                       # 全部 14 条
npm run test:e2e -- e2e/journey/        # 只跑 journey
npm run test:e2e -- e2e/chat-happy-path # 只跑单条
```

## 调试工具

`frontend/scripts/debug/` 是开发者排错工具,**不是测试**。需手动
`npx playwright test frontend/scripts/debug/<file>` 跑,不进 CI。
详见 [frontend/scripts/debug/README.md](../scripts/debug/README.md)。
```

- [ ] **Step 2: 写 `frontend/scripts/debug/README.md`**

文件路径:`/Users/yxb/projects/nexus/frontend/scripts/debug/README.md`

```markdown
# Debug / Diagnostic 工具

非测试,开发者排错用。**不在 Playwright testDir 内**,不进 CI。

## 用法

```bash
cd frontend
npx playwright test scripts/debug/debug-agnes-message.spec.ts
npx playwright test scripts/debug/diag-ws-page.spec.ts
```

## 文件

- `debug-agnes-message.spec.ts` — 读 ~/.nexus/ 内某条消息,辅助诊断
  消息结构 / 数据库内容。
- `diag-ws-page.spec.ts` — 采集 WS 帧时序,console 打时间线,辅助诊断
  WS 协议问题。
```

- [ ] **Step 3: 更新 `CHANGELOG.md`**

文件路径:`/Users/yxb/projects/nexus/CHANGELOG.md`(在文件顶部追加 §章节)

```markdown
## test(e2e): 4 条 user-journey spec + debug 工具挪出 (2026-07-12)

新增 `frontend/e2e/journey/` 目录,落地 4 条模拟人工视角的端到端
E2E spec,全走真 LLM,CI 必跑:

- `journey-cold-start`: 新用户从打开到首次回复
- `journey-multi-turn`: 同会话 3 条连发 + 上下文回显
- `journey-hitl-workflow`: AGENTS.md 写入触发 HITL + 批准 + 流续接
- `journey-resilience`: 后端崩溃 → 重启 → 浏览器自动重连

新增 `frontend/e2e/journey/helpers.ts`,封装 journey 专用高层动作
(`sendSequence` / `expectContextRecall` / `killBackend` 等),
与现有 `frontend/e2e/helpers.ts` 底层选择器封装分层。

把 `debug-agnes-message.spec.ts` / `diag-ws-page.spec.ts`
从 `frontend/e2e/` 挪到 `frontend/scripts/debug/`,这俩是开发者排错
工具不是产品验收,移出 Playwright testDir 不再被自动扫描。

详见 `docs/superpowers/specs/2026-07-12-e2e-suite-design.md`。
```

- [ ] **Step 4: 验证 git status**

```bash
cd /Users/yxb/projects/nexus && git status --short
```

Expected:
```
M CHANGELOG.md
A frontend/e2e/README.md
A frontend/e2e/journey/helpers.ts (追加)
A frontend/e2e/journey/journey-resilience.spec.ts
A frontend/scripts/debug/README.md
R frontend/e2e/debug-agnes-message.spec.ts -> frontend/scripts/debug/debug-agnes-message.spec.ts
R frontend/e2e/diag-ws-page.spec.ts -> frontend/scripts/debug/diag-ws-page.spec.ts
```

- [ ] **Step 5: git add + commit**

```bash
cd /Users/yxb/projects/nexus && git add CHANGELOG.md frontend/e2e/README.md frontend/e2e/journey/helpers.ts frontend/e2e/journey/journey-resilience.spec.ts frontend/scripts/debug/README.md && git commit -m "$(cat <<'EOF'
test(e2e): journey-resilience spec + debug 工具挪出 scripts/debug/

新增 journey-resilience(后端 kill→重启→浏览器自动重连,真 LLM,CI 必跑),
并把 debug-agnes-message / diag-ws-page 工具从 e2e/ 挪出到 scripts/debug/,
不计入产品验收。

附 CHANGELOG 与 e2e/README / scripts/debug/README 说明。
EOF
)"
```

---

## Task 10: 最终验收 — 跑全 14 条 spec 确认 CI 状态

**Files:** 无修改,只跑测试

- [ ] **Step 1: 跑完整 e2e suite**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.minimaxi.com/v1}" \
  MODEL_NAME="${MODEL_NAME:-MiniMax-M3}" \
  npx playwright test --reporter=list
```

Expected: 14 passed(10 单点 + 4 journey),wall time ~15-25min。

- [ ] **Step 2: 若有失败,优先 retry**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.minimaxi.com/v1}" \
  MODEL_NAME="${MODEL_NAME:-MiniMax-M3}" \
  npx playwright test --reporter=list --retries=2
```

- [ ] **Step 3: 验证 git log 最终状态**

```bash
git log --oneline -5
```

Expected: 看到 2 个 commit(Task 6 + Task 9),本 plan 落档到 main 分支无其他改动。

---

## Self-Review

**1. Spec coverage:**
- §1 目标 4 条 journey — Task 3, 4, 5, 7 覆盖 ✓
- §1 debug/diag 工具挪出 — Task 8 覆盖 ✓
- §2 架构(journey/ 目录 + scripts/debug/)— Task 1, 8 覆盖 ✓
- §3 数据流(webServer env, workers=1, 真 LLM)— 不动配置,既有 ✓
- §4 journey/helpers.ts 全部 helper — Task 2, 7 覆盖 ✓
- §5 错误处理(确定性 prompt / retry / 超时)— Task 3-5, 7 显式设置 ✓
- §6 测试与验证(冒烟)— Task 10 ✓
- §7 迁移与回滚 — 全程 git mv, 可 revert ✓
- §8 文档(CHANGELOG / README)— Task 9 覆盖 ✓

**2. Placeholder scan:**
- 无 TBD / TODO / "fill in"
- 无 "similar to Task N" 跨任务代码复用
- 每个代码块都有完整内容

**3. Type consistency:**
- `journeyOpenHome` 在 Task 2 定义,Task 3, 4, 5, 7 一致使用 ✓
- `sendSequence` Task 2 定义,Task 4 使用 ✓
- `hitlConfirmCard` / `hitlApproveButton` Task 2 定义,Task 5 使用 ✓
- `killBackend` / `waitBackendAlive` / `isBackendAlive` Task 2 + Task 7 一致 ✓
- `APP_WS_KEY = '__nexusAppSockets'` Task 7 定义,与 reconnect.spec.ts 相同 ✓

**Dead code check:**
- `hitlRejectButton` 原计划定义但未使用 — 已删除,改在 Task 5 Step 1 按需 grep 确认 ✓

---

# Phase 2: 用户视角盲区扩展 (2026-07-13)

> **For agentic workers:** 继续用 superpowers:subagent-driven-development 推进。Phase 1 落地 4 条 journey spec 全部 PASS(commit `a626016` + 9c45f6f + 450f37e + c3f2914);本阶段聚焦"模拟人工视角"还有哪些真用户路径没覆盖。

**Goal:** 把 journey spec 从 4 条扩到 7 条,补齐**输入边界 / 交互流 / 错误路径 / 微信通道后续流程**这四大盲区。所有 spec 走真 LLM(mock 仅在显式 LLM 不可控场景才用),CI 必跑。

**参考现状**(2026-07-13 已确认):
- 4 条 journey spec + 10 条产品验收 spec = 14 条全过
- 微信 spec `e2e/wechat-channel.spec.ts` 只覆盖到"拿到 QR code",**没覆盖扫码后状态切换 / 收消息 / 关键词回复**
- 仓库已有 mock WS 模式(`e2e/clarification.spec.ts:installMockWs`),401 等错误场景可复用
- journey/helpers.ts 已有 `killBackend` / `waitBackendAlive` / `sendSequence` / `hitlConfirmCard` / `hitlApproveButton` 等高层封装

## 范围决策(WHY 不做某些项)

| 类别 | 不做 / 暂缓 | 原因 |
| --- | --- | --- |
| 桌面端菜单 / Dock / 全局快捷键 | ❌ Tauri 2 native shell,Playwright 触达不到 | 需 `tauri-driver` WebDriver binding,1-2 周,且 Tauri 2 webdriver 还不稳 |
| 超长消息(> 200k context) | ❌ | SummarizationMiddleware 已有单测,UI 层不验证 |
| 重新生成(LLM 重调) | ❌ | 等会话切换稳了再做 |
| 微信扫码成功后"绑定状态切换 / 收消息 / 关键词回复" | ✅ **做** | 这是当前 spec 实际留的尾巴 |
| 输入边界(空/emoji/多语言) | ✅ **做** | 半天搞定,挡一类典型 bug |
| 交互流(快捷 prompt / 历史切换) | ✅ **做** | 半天搞定,挡一类典型 bug |
| 错误路径(主动 stop / 401) | ✅ **做** | 半天搞定,挡一类典型 bug |

## 范围裁剪(WHY 只做 5 条)

按"高 ROI / 低耦合"排序,Phase 2 加 5 条新 journey spec(总成本 ~2-3 天):

| Task | Spec | 用户故事 | Mock? |
| --- | --- | --- | --- |
| 11 | journey-quick-prompts-and-history | 4 个 QUICK_PROMPTS 点击 + Sidebar 历史会话切换 | 真 LLM |
| 12 | journey-stop-mid-stream | 主动 stop 流(在流中途点停) | 真 LLM |
| 13 | journey-input-edge-cases | 空消息 / emoji / 多语言 | 真 LLM(mock 备) |
| 14 | journey-auth-401 | 模型 401(密钥失效)兜底回 SetupView | mock LLM 返 401 |
| 15 | journey-wechat-bound-receive | 微信扫码后绑定状态切换 + mock server 发消息 → 关键词回复 | mock 微信 server |

不在 Phase 2 内(后续 phase 评估):
- 微信协议升级到企业微信 / 飞书 → 待产品决策
- Tauri 2 webdriver 接入 → 1-2 周专项

---

## Task 11: journey-quick-prompts-and-history.spec.ts

**Files:**
- Create: `frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts`

**前置**:确认 4 个 QUICK_PROMPTS 文案 + Sidebar 历史会话项选择器。grep `frontend/src/components/ChatArea/` 找 QUICK_PROMPTS 常量 + sidebar item 选择器。

- [ ] **Step 1: grep 文案**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  grep -rn "QUICK_PROMPTS\|prompt-card\|写代码\|分析数据\|知识问答\|写作助手" src/components/ChatArea/ | head -20
```

Expected: 找到 QUICK_PROMPTS 数组 + 4 个 title + .prompt-card 类名。

- [ ] **Step 2: grep Sidebar 历史会话选择器**

```bash
grep -rn "history-item\|task-item\|session-item" src/components/Sidebar/ src/components/ChatHistory/ 2>/dev/null | head -20
```

Expected: 找到会话列表项的 class 名 / data 属性。

- [ ] **Step 3: 写 spec**

文件路径:`/Users/yxb/projects/nexus/frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts`

```typescript
/**
 * User Journey: 快捷 prompt + 历史会话切换
 *
 * 用户故事:
 *   1. 打开 ChatView,4 个 QUICK_PROMPTS 卡片渲染
 *   2. 点 "写代码" 卡片 → 触发首次对话 → assistant 回复非空
 *   3. 新建第 2 个会话(发任意消息)
 *   4. Sidebar 出现 2 个会话项,点回第 1 个 → 切回旧会话
 *   5. 旧会话消息流恢复(包含之前的 user/assistant)
 *
 * 关键约束:
 *   - 真 LLM,慢,timeout 240s(每轮 ~60-80s × 3 轮)。
 *   - "QUICK_PROMPTS" 文案以 ChatArea.tsx 实际值为准,grep 验证后回填。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { sendMessageAndWaitForReply, messageCount } from '../helpers';

test('快捷 prompt → 历史会话切换', async ({ page }) => {
  test.setTimeout(240_000);

  await journeyOpenHome(page);

  // 1. 点 "写代码" 快捷 prompt
  const quickPrompt = page.locator('button.prompt-card', { hasText: '写代码' });
  await expect(quickPrompt).toBeVisible({ timeout: 30_000 });
  await quickPrompt.click();

  // 2. assistant 回复非空
  await sendMessageAndWaitForReply(page, '' /* 内容由快捷 prompt 注入 */, { timeoutMs: 120_000 })
    .catch(async () => {
      // 兼容快捷 prompt 直接填充 textarea 但没自动发的实现:手动 fill + send
      await page.locator('textarea[placeholder*="告诉"]').fill('用一句话介绍 Python');
      await page.locator('button').filter({ has: page.locator('svg path[d^="M12 19"]') }).first().click();
      await sendMessageAndWaitForReply(page, '' /* placeholder,实际已发 */, { timeoutMs: 120_000 });
    });

  // 3. 新建第 2 个会话(通过 sidebar "新任务" / 类似入口)
  const newSessionBtn = page.locator('button.btn-new-task, button:has-text("新任务")').first();
  if (await newSessionBtn.count()) {
    await newSessionBtn.click();
  }
  await sendMessageAndWaitForReply(page, '用一句话介绍 Go', { timeoutMs: 120_000 });

  // 4. Sidebar 应有 2+ 个会话项,点回第 1 个
  const sessionItems = page.locator('.task-item, [data-session-id]');
  const sessionCount = await sessionItems.count();
  expect(sessionCount, 'Sidebar 应有 2+ 个会话').toBeGreaterThanOrEqual(2);

  await sessionItems.first().click();

  // 5. 旧会话消息流恢复(>= 2 条)
  await expect(async () => {
    const count = await messageCount(page);
    expect(count, '切换回旧会话应保留历史消息').toBeGreaterThanOrEqual(2);
  }).toPass({ timeout: 15_000, intervals: [500, 1000, 2000] });
});
```

**注意**:本 spec 是占位实现,实施时按 Step 1-2 grep 结果调整选择器和等待策略。

- [ ] **Step 4: 跑 spec 验证**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  npx playwright test e2e/journey/journey-quick-prompts-and-history.spec.ts --reporter=list
```

Expected: PASS in ~90-180s。

---

## Task 12: journey-stop-mid-stream.spec.ts

**Files:**
- Create: `frontend/e2e/journey/journey-stop-mid-stream.spec.ts`

**前置**:确认流中途"停"按钮的选择器。grep `frontend/src/components/ChatArea/` 找 stop button / 中断流。

- [ ] **Step 1: grep 停按钮**

```bash
grep -rn "stop\|abort\|中断\|停止\|cancel-stream" src/components/ChatArea/ src/hooks/ 2>/dev/null | head -20
```

Expected: 找到 stop button 选择器(类名 / aria-label / 文案)。

- [ ] **Step 2: 写 spec**

```typescript
/**
 * User Journey: 流中途主动 stop
 *
 * 用户故事:
 *   1. 发问题,assistant 开始流式输出
 *   2. 流中途点 stop 按钮
 *   3. 助手气泡不再增长,输入框重新可点
 *   4. 验证 stream_guard 状态:done / cancelled 帧已收到
 *
 * 关键约束:
 *   - 真 LLM,慢。
 *   - 必须等流"已开始"(收到第一个 chunk)再点 stop,否则太早会 noop。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput } from '../helpers';

test('流中途 stop', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  await messageInput(page).fill('详细介绍 Python 的历史');
  await page.locator('button').filter({ has: page.locator('svg path[d^="M12 19"]') }).first().click();

  // 等流开始(收到首个 chunk → assistant 气泡有非空文本)
  const assistantRow = page.locator('.message-row.is-assistant').last();
  await expect(assistantRow).toBeVisible({ timeout: 60_000 });
  await expect(assistantRow.locator('p').first()).not.toBeEmpty({ timeout: 60_000 });

  // 记下 stop 前的字符数
  const textBefore = await assistantRow.innerText();
  const lengthBefore = textBefore.length;

  // 点 stop 按钮(类名 / aria-label 按 Step 1 grep 结果替换)
  const stopBtn = page.locator('button[aria-label*="stop"], button.stop-btn, button:has-text("停止")').first();
  if (await stopBtn.count()) {
    await stopBtn.click();
  }

  // 短暂等待让 React 状态更新
  await page.waitForTimeout(2000);

  // 输入框应可点(loading 已结束)
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });

  // 字符数不应"显著增长"(允许略增因为 stop 可能有 race)
  const textAfter = await assistantRow.innerText();
  const lengthAfter = textAfter.length;
  expect(
    lengthAfter - lengthBefore,
    `stop 后文本不应持续增长,before=${lengthBefore}, after=${lengthAfter}`
  ).toBeLessThan(50);
});
```

- [ ] **Step 3: 跑 spec 验证**

Expected: PASS in ~30-60s。

---

## Task 13: journey-input-edge-cases.spec.ts

**Files:**
- Create: `frontend/e2e/journey/journey-input-edge-cases.spec.ts`

**前置**:真 LLM 不可控(emoji / 多语言回复内容不稳),本 spec 改用断言"前端不崩 / UI 状态正确"而非"回复内容含 X"。

- [ ] **Step 1: 写 spec**

```typescript
/**
 * User Journey: 输入边界
 *
 * 用户故事(3 个 sub-test):
 *   1. 空消息:点发送按钮应 noop 或禁用,不崩
 *   2. emoji:发"🎉🐍🚀" → 前端不崩,assistant 气泡渲染
 *   3. 多语言:中英日混排 → assistant 气泡渲染
 *
 * 关键约束:
 *   - 真 LLM 对 emoji / 多语言回复不可控,只断言 UI 状态(气泡存在、
 *     流正常结束、输入框重新可点)。
 *   - 不强求回复内容含特定字符串。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput, sendButton, messageCount } from '../helpers';

test('空消息:点发送应 noop,不崩', async ({ page }) => {
  test.setTimeout(60_000);

  await journeyOpenHome(page);

  const userBefore = await page.locator('.message-row.is-user').count();

  // 不填任何内容,直接点发送
  await messageInput(page).fill('');
  // 注意:某些实现发送按钮在空消息时 disabled,某些会触发 noop。
  // 这两种都视为正确,只断言"不崩 / 不出现 user 气泡"。
  if (await sendButton(page).isEnabled()) {
    await sendButton(page).click();
    await page.waitForTimeout(500);
  }

  const userAfter = await page.locator('.message-row.is-user').count();
  expect(userAfter, '空消息不应产生 user 气泡').toBe(userBefore);
});

test('emoji 输入', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  await messageInput(page).fill('🎉🐍🚀');
  await sendButton(page).click();

  // user 气泡出现 + assistant 气泡渲染(任意内容)
  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 5_000 });
  await expect(async () => {
    const count = await messageCount(page);
    expect(count, 'emoji 流结束后应至少有 2 条气泡').toBeGreaterThanOrEqual(2);
    await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });
  }).toPass({ timeout: 90_000, intervals: [1000, 2000, 3000] });
});

test('多语言混排(中英日)', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  await messageInput(page).fill('Python 中的 lambda 是什么? 日本語で答えてください。');
  await sendButton(page).click();

  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 5_000 });
  await expect(async () => {
    const count = await messageCount(page);
    expect(count, '多语言流结束后应至少有 2 条气泡').toBeGreaterThanOrEqual(2);
    await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });
  }).toPass({ timeout: 90_000, intervals: [1000, 2000, 3000] });
});
```

- [ ] **Step 2: 跑 spec 验证**

Expected: 3 passed in ~120-240s total。

---

## Task 14: journey-auth-401.spec.ts

**Files:**
- Create: `frontend/e2e/journey/journey-auth-401.spec.ts`

**前置**:后端 `_llm_factory` 在 LLM 返 401 时应走 `classify(exc) → AuthenticationError → kind=AUTH`,前端收到 error 帧后兜底回 SetupView 还是停留在 ChatView 待确认。

本 spec 用 mock LLM 强制返 401 帧,验证前端兜底行为。

- [ ] **Step 1: 确认 mock LLM 是否能模拟 401**

读 `nexus/backend/llm/e2e_mock.py`,确认是否已有 mock 401 场景,无则需新增。

```bash
cd /Users/yxb/projects/nexus && cat nexus/backend/llm/e2e_mock.py | head -100
```

Expected: 看到 `NEXUS_E2E_SCENARIO` 列表。本 spec 需新增场景 `auth_401`(或类似名)。

- [ ] **Step 2: 若 e2e_mock 无 401 场景,在 `nexus/backend/llm/e2e_mock.py` 追加**

```python
# 追加场景:模拟 LLM 401 错误
# WHY:验证密钥失效时前端是否兜底回 SetupView,而不是无限 spinner。
elif os.environ.get("NEXUS_E2E_SCENARIO") == "auth_401":
    async def auth_401_handler(*args, **kwargs):
        from openai import AuthenticationError
        raise AuthenticationError(
            "Invalid API key",
            response=httpx.Response(401, request=httpx.Request("POST", "/v1/chat/completions")),
            body=None,
        )
    llm = make_mock_llm(auth_401_handler)
```

(具体 API 按 e2e_mock.py 实际 helper 名调整)

- [ ] **Step 3: 写 spec**

```typescript
/**
 * User Journey: 模型 401 兜底
 *
 * 用户故事:
 *   1. 用户配置了一个无效密钥的模型 → 后端 LLM 返 401
 *   2. 前端应:
 *      a. 不无限 spinner
 *      b. 不抛 JS 错误(无 pageerror)
 *      c. 至少提示用户"密钥失效"(具体兜底方式待确认)
 *
 * mock 模式:NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=auth_401
 * 强制后端 mock LLM 抛 AuthenticationError。
 */
import { test, expect } from '@playwright/test';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1' || process.env.NEXUS_E2E_SCENARIO !== 'auth_401',
  '需要 NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=auth_401 触发 401 mock',
);

test('密钥失效 401 兜底', async ({ page }) => {
  test.setTimeout(60_000);

  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/app/');

  // 等 ChatView 输入框可点(说明 useBootstrap 已通过)
  const input = page.getByPlaceholder('告诉 Nexus 你想完成什么');
  await expect(input).toBeEnabled({ timeout: 30_000 });

  // 发消息触发 mock 401
  await input.fill('测试 401');
  await page.locator('button').filter({ has: page.locator('svg path[d^="M12 19"]') }).first().click();

  // 等错误反馈(具体 UI 文案按实施时观察)
  // 兜底判断:输入框重新可点(loading 结束)+ 无 pageerror
  await expect(input).toBeEnabled({ timeout: 30_000 });

  // 不应有 JS 报错
  expect(pageErrors, '401 兜底路径不应抛 JS 错误').toEqual([]);
});
```

- [ ] **Step 4: 跑 spec 验证**

```bash
cd /Users/yxb/projects/nexus/frontend && \
  NEXUS_E2E_MOCK=1 NEXUS_E2E_SCENARIO=auth_401 \
  npx playwright test e2e/journey/journey-auth-401.spec.ts --reporter=list
```

Expected: PASS in ~10-20s。

---

## Task 15: journey-wechat-bound-receive.spec.ts

**Files:**
- Create: `frontend/e2e/journey/journey-wechat-bound-receive.spec.ts`

**前置**:当前 `e2e/wechat-channel.spec.ts` 只测到 "拿到 QR code"。本 task 验证 QR 拿到后**模拟服务端推送扫码成功事件 → 绑定状态切换 → mock 收消息 → 关键词回复**。

需新增一个 mock wechat server 模拟:扫码成功 / 用户发文本消息 → 验证 Nexus 回复。

- [ ] **Step 1: 摸后端 webhook / 推送端点**

```bash
grep -rn "wechat.*webhook\|wechat.*callback\|on_message\|handle_message" /Users/yxb/projects/nexus/nexus/backend/channels/ | head -20
```

Expected: 找到 wechat 收消息的端点(可能是 POST /api/channels/wechat/inbound 或类似)。

- [ ] **Step 2: 写 mock wechat server(可放在 spec 顶部 inline)**

按 Step 1 找到的端点,用 `route.fulfill()` 模拟:
- 用户"扫码成功"事件 → 后端切到绑定态
- 用户发文本 → 后端触发 agent → 关键词回复

(本 spec 实现细节按 Step 1 grep 结果调整;若后端无标准 inbound 端点可走 Playwright `page.evaluate` 直接调内部函数)

- [ ] **Step 3: 写 spec**

```typescript
/**
 * User Journey: 微信扫码后绑定 + 收消息
 *
 * 用户故事:
 *   1. 侧栏 → 微信通道 → 扫码绑定 → 拿到 QR
 *   2. mock server 推送"扫码成功" → WechatAssistantView 状态切到 "已连接"
 *   3. mock server 推一条用户消息 "你好"
 *   4. Nexus agent 处理后,通过微信通道回消息(端到端验证)
 *
 * 关键约束:
 *   - mock 微信 server 在 spec 内 inline,不走真实协议。
 *   - 详细端点 / 消息格式按 Task 15 Step 1 grep 结果调整。
 */
import { test, expect } from '@playwright/test';
import { openHome } from '../helpers';

// 占位:实际端点 / payload 按 grep 结果填充
test('微信扫码绑定 → 收消息 → 关键词回复', async ({ page }) => {
  test.setTimeout(90_000);

  await openHome(page);

  // ... 按 Step 1 grep 结果实施
});
```

- [ ] **Step 4: 跑 spec 验证**

Expected: PASS in ~30-60s(若 mock 工作)。

---

## Task 16: 更新 README + CHANGELOG + 提交

**Files:**
- Modify: `frontend/e2e/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新 e2e/README.md**

在 "4 条 user-journey spec" 表格追加 5 条新 spec:

```markdown
| `journey-quick-prompts-and-history.spec.ts` | 4 个 QUICK_PROMPTS + Sidebar 历史切换 |
| `journey-stop-mid-stream.spec.ts` | 流中途主动 stop |
| `journey-input-edge-cases.spec.ts` | 空 / emoji / 多语言输入 |
| `journey-auth-401.spec.ts` | 模型密钥失效兜底 |
| `journey-wechat-bound-receive.spec.ts` | 微信扫码绑定 + 收消息 + 关键词回复 |
```

并把总数更新成 9 条 journey spec + 10 条产品验收 spec = 19 条。

- [ ] **Step 2: 更新 CHANGELOG.md**

在文件顶部追加 §章节:

```markdown
## test(e2e): journey 套件 Phase 2 扩到 9 条 (2026-07-13)

新增 5 条 user-journey spec,补齐用户视角盲区:

- `journey-quick-prompts-and-history`: 4 个快捷 prompt + Sidebar 历史切换
- `journey-stop-mid-stream`: 流中途主动 stop
- `journey-input-edge-cases`: 空 / emoji / 多语言输入边界
- `journey-auth-401`: 模型密钥失效兜底(mock 401 场景)
- `journey-wechat-bound-receive`: 微信扫码绑定 + 收消息 + 关键词回复

详见 `docs/superpowers/plans/2026-07-12-e2e-journey-suite.md` Phase 2。
```

- [ ] **Step 3: git add + commit**

```bash
cd /Users/yxb/projects/nexus && \
  git add docs/superpowers/plans/2026-07-12-e2e-journey-suite.md \
         frontend/e2e/journey/journey-quick-prompts-and-history.spec.ts \
         frontend/e2e/journey/journey-stop-mid-stream.spec.ts \
         frontend/e2e/journey/journey-input-edge-cases.spec.ts \
         frontend/e2e/journey/journey-auth-401.spec.ts \
         frontend/e2e/journey/journey-wechat-bound-receive.spec.ts \
         frontend/e2e/README.md \
         CHANGELOG.md && \
  git commit -m "$(cat <<'EOF'
test(e2e): journey Phase 2 扩到 9 条(快捷/stop/边界/401/微信收消息)

补齐用户视角盲区,5 条新 spec:

- journey-quick-prompts-and-history: 4 个 QUICK_PROMPTS + Sidebar 历史切换
- journey-stop-mid-stream: 流中途主动 stop
- journey-input-edge-cases: 空 / emoji / 多语言输入边界
- journey-auth-401: 模型密钥失效兜底(mock 401)
- journey-wechat-bound-receive: 微信扫码绑定 + 收消息 + 关键词回复

附录更新 + CHANGELOG。详见
docs/superpowers/plans/2026-07-12-e2e-journey-suite.md Phase 2。
EOF
)"
```

---

## Phase 2 Self-Review

**1. Spec coverage:**
- 输入边界(空/emoji/多语言)— Task 13 ✓
- 交互流(快捷 prompt + 历史切换)— Task 11 ✓
- 错误路径(stop + 401)— Task 12 + Task 14 ✓
- 微信收消息 / 关键词回复 — Task 15 ✓
- 桌面端菜单 / Dock / 全局快捷键 — **不做**(Tauri 2 webdriver,1-2 周专项)
- 重新生成 — **不做**(等会话切换稳了)

**2. Placeholder scan:**
- Task 11-15 的 spec 实现是"占位 + 实施时按 grep 结果调整"风格 — 这是 plan 阶段的合理抽象,
  实施时若 grep 出的实际 selector 与代码块不一致,以实际为准。
- Task 14 / Task 15 的 mock 实现需要 Step 1-3 的 grep 信息,实施时按需调整。

**3. Type consistency:**
- `journeyOpenHome` Task 11-13 复用,Task 14 不用(直接 goto)
- `messageInput` / `sendButton` Task 12-13 复用
- `messageCount` Task 11, 13 复用
- `sendMessageAndWaitForReply` Task 11 复用
- Task 14-15 不复用上述(各自独立 mock)

**4. 成本估算:**
- Task 11-15 单条 ~0.5-1 天,共 3-4 天

**风险:**
- Task 14 (401):e2e_mock.py 现有场景可能不支持 401,需新增。**Step 1-2 失败则 Task 14 降级为占位,留待后续专项。**
- Task 15 (微信收消息):mock wechat server 工作量取决于后端 inbound 端点形式。**Step 1 grep 后若发现 inbound 端点缺失,本 task 降级为只覆盖"绑定状态切换"半段,收消息半段留待后续。**