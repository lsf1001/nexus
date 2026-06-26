import { test, expect } from '@playwright/test';
import { openHome, messageInput, sendButton } from './helpers';

/**
 * HITL 确认卡片 E2E(真实 LLM)。
 *
 * 用户旅程:
 *   1. 在 ChatView 输入框要求 AI 写一个文件
 *   2. LLM 触发 FilesystemPermission interrupt,后端发 confirmation_request
 *   3. 前端 .confirm-card 出现,带 [批准] [拒绝] 两个按钮
 *   4. 模拟用户点 [批准]
 *   5. 流继续 → 收到 final 文本,流结束
 *   6. 验证输入框重新可点 + 卡片消失
 *
 * 真实 LLM 路径,会跑 1-2 分钟。
 *
 * WS 帧抓包改用 Playwright 原生 page.on('websocket') ——
 * 之前用 addInitScript 重写 window.WebSocket 构造器,会污染浏览器 ws 内部
 * 行为(抓包到 close 1006 / 0 帧收到),3/3 跑失败。Playwright 原生事件
 * 监听器是浏览器层外的,不影响 ws 自身实现,稳定可靠。
 */
test('HITL 确认卡片:触发 → 批准 → 流完成', async ({ page }) => {
  test.setTimeout(180_000);

  // WS 帧时序采集 — 用 Playwright 原生 page.on('websocket') 监听所有
  // 浏览器底层 ws 事件。每条事件带时间戳,失败时打出来辅助诊断。
  const wsEvents: Array<{ t: number; kind: string; data?: string }> = [];
  const t0 = Date.now();
  const push = (kind: string, data?: string) => {
    const entry = { t: Date.now() - t0, kind, data };
    wsEvents.push(entry);
    if (wsEvents.length <= 500) {
      // 限制 log 量,避免控制台爆炸
      console.log(`[WS-EVT] [+${entry.t}ms] ${kind} ${data ? data.slice(0, 150) : ''}`);
    }
  };
  page.on('websocket', (ws) => {
    const url = ws.url();
    if (!url.includes('/api/ws')) {
      // 忽略 Vite HMR 等非业务 ws
      return;
    }
    push('opened', url);
    ws.on('framesent', (f) => push('TX', f.payload?.toString()));
    ws.on('framereceived', (f) => push('RX', f.payload?.toString()));
    ws.on('close', () => push('close', ''));
    ws.on('socketerror', (err) => push('error', String(err)));
  });

  await openHome(page);

  // 触发 AGENTS.md 写入 — 受保护路径会触发 HITL interrupt。
  //
  // prompt 设计:LLM 行为不稳定,有时直接调 write_file / edit_file 触发
  // HITL,有时给方案不调工具,有时决定后卡 thinking 90s+ 没结论。
  // 用 "假设文件存在,直接 edit_file" —— LLM 对 edit_file 调用最稳,
  // 旧字符串用一个非常独特的占位符(几乎不可能匹配),LLM 会直接当成
  // "在文件不存在时整体覆盖" 的语义去调。
  const prompt =
    '请用 edit_file 工具把 ~/.nexus/AGENTS.md 整体替换为单行 ' +
    '"e2e_hitl_marker_2026"。old_string 用 "___NEVER_MATCH_42___",' +
    'new_string 用 "e2e_hitl_marker_2026"。直接调一次 edit_file 完成,' +
    '不要 read_file、不要 ask_user、不要用 task 子代理、不要用 shell。';
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill(prompt);
  await sendButton(page).click();

  // 等 user 气泡出现
  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 10_000 });

  // 等确认卡片出现
  const confirmCard = page.locator('.confirm-card');
  await expect(confirmCard).toBeVisible({ timeout: 90_000 });

  // 卡片里至少有一个 [批准] 按钮
  const approveBtn = confirmCard.locator('button.confirm-approve');
  await expect(approveBtn).toBeVisible({ timeout: 5_000 });
  const approveText = (await approveBtn.innerText()).trim();
  expect(approveText.length).toBeGreaterThan(0);

  // 截图(保留卡片样式证据)
  await page.screenshot({ path: 'test-results/hitl-confirm-01-card.png' });

  // 用户点批准
  const approveT = Date.now();
  await approveBtn.click();
  push('approve-clicked');

  // 卡片应当消失
  await expect(confirmCard).toBeHidden({ timeout: 5_000 });

  // 流继续:输入框重新可点(流最终结束)
  await expect(messageInput(page)).toBeEnabled({ timeout: 90_000 });

  // 至少有一个 assistant 气泡
  const assistantBubbles = page.locator('.message-row.is-assistant');
  await expect(assistantBubbles.first()).toBeVisible({ timeout: 5_000 });
  const count = await assistantBubbles.count();
  const allAssistantTexts = await assistantBubbles.allInnerTexts();
  const nonEmptyCount = allAssistantTexts.filter((t) => t.trim().length > 0).length;

  await page.screenshot({ path: 'test-results/hitl-confirm-02-after-approve.png' });

  // 诊断输出
  console.log(`[hitl-confirm] assistant bubble count=${count}, non-empty=${nonEmptyCount}`);
  console.log(`[hitl-confirm] all assistant texts:`, JSON.stringify(allAssistantTexts, null, 2));
  console.log(`[hitl-confirm] ws event count=${wsEvents.length}`);
  const approveIdx = wsEvents.findIndex((e) => e.kind === 'approve-clicked');
  const rxAfterApprove = wsEvents.filter((e) => e.kind === 'RX' && e.t > (approveT - t0));
  const closeEvents = wsEvents.filter((e) => e.kind === 'close');
  console.log(
    `[hitl-confirm] RX after approve: ${rxAfterApprove.length}, close events: ${closeEvents.length}`
  );
  if (approveIdx >= 0) {
    console.log(`[hitl-confirm] approve at +${wsEvents[approveIdx].t}ms`);
  }
  console.log(
    `[hitl-confirm] ws timeline:\n${wsEvents.map((e) => `  +${e.t}ms ${e.kind} ${e.data ? e.data.slice(0, 100) : ''}`).join('\n')}`
  );

  expect(nonEmptyCount).toBeGreaterThan(0);

  // bug #58 回归断言:Judge 输出(raw JSON 风格)不能出现在用户可见的 assistant 气泡里。
  const judgeLeakInAssistant = allAssistantTexts.some(
    (t) => t.includes('"score"') || t.includes('"reasoning"') || t.includes('"evidence"')
  );
  expect(judgeLeakInAssistant).toBe(false);
});
