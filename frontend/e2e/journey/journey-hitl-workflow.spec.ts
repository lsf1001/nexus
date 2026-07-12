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