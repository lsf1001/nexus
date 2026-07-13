/**
 * User Journey: 输入边界(空 / emoji / 多语言)
 *
 * 用户故事(3 个 sub-test):
 *   1. 空消息:点发送按钮 noop(Composer.tsx:55 `disabled || !value.trim()`),
 *     不应出现 user 气泡
 *   2. emoji:发"🎉🐍🚀" → 前端不崩 + 流正常完成
 *   3. 多语言:中英日混排 → 前端不崩 + 流正常完成
 *
 * 关键约束:
 *   - 真 LLM 对 emoji / 多语言回复内容不可控,只断言 UI 状态(气泡存在、
 *     流正常结束、输入框重新可点)。
 *   - 不强求回复内容含特定字符串。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput, sendButton, messageCount } from '../helpers';

test('空消息:不产生 user 气泡', async ({ page }) => {
  test.setTimeout(60_000);

  await journeyOpenHome(page);

  const userBefore = await page.locator('.message-row.is-user').count();

  // 1. 不填内容,直接尝试点发送
  await messageInput(page).fill('');
  // 强制点(即使 disabled,force=true 也算"用户操作")→ 应 noop
  if (await sendButton(page).isEnabled().catch(() => false)) {
    await sendButton(page).click();
    await page.waitForTimeout(500);
  } else {
    // disabled 是正确行为,直接确认
    await expect(sendButton(page)).toBeDisabled();
  }

  const userAfter = await page.locator('.message-row.is-user').count();
  expect(userAfter, '空消息不应产生 user 气泡').toBe(userBefore);
});

test('emoji 输入:流正常完成', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  await messageInput(page).fill('🎉🐍🚀');
  await sendButton(page).click();

  // user 气泡出现
  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 5_000 });

  // 流正常结束:气泡数 >= 2 + 输入框重新可点
  await expect(async () => {
    const count = await messageCount(page);
    expect(count, 'emoji 流结束后应至少有 2 条气泡').toBeGreaterThanOrEqual(2);
    await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });
  }).toPass({ timeout: 90_000, intervals: [1000, 2000, 3000] });
});

test('多语言混排(中英日):流正常完成', async ({ page }) => {
  test.setTimeout(120_000);

  await journeyOpenHome(page);

  await messageInput(page).fill(
    'Python 中的 lambda 是什么? 日本語で答えてください。',
  );
  await sendButton(page).click();

  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 5_000 });

  await expect(async () => {
    const count = await messageCount(page);
    expect(count, '多语言流结束后应至少有 2 条气泡').toBeGreaterThanOrEqual(2);
    await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });
  }).toPass({ timeout: 90_000, intervals: [1000, 2000, 3000] });
});
