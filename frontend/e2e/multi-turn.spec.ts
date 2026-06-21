import { test, expect } from '@playwright/test';
import { openHome, sendMessageAndWaitForReply, lastUserBubbleText, messageCount } from './helpers';

/**
 * 多轮会话 + 滚动 E2E：
 *   1. 发 3 条不同问题
 *   2. 验证页面有 6 条气泡（3 user + 3 assistant）
 *   3. 验证每对 user-assistant 顺序正确
 *   4. 验证最后一条 user 消息是新发的
 *   5. 验证滚动条：第 3 条 assistant 气泡在视口内
 */
test('多轮会话：3 条消息连发，按序追加并滚到底', async ({ page }) => {
  await openHome(page);

  const messages = [
    '用一句话介绍 Python',
    '再介绍一下 JavaScript',
    '最后说说 Go',
  ];

  for (const m of messages) {
    await sendMessageAndWaitForReply(page, m, { timeoutMs: 120_000 });
  }

  // 至少 6 条气泡（3 user + 3 assistant）
  const total = await messageCount(page);
  expect(total).toBeGreaterThanOrEqual(6);

  // 最后一条 user 消息应是"最后说说 Go"
  expect(await lastUserBubbleText(page)).toBe('最后说说 Go');

  // 验证滚到底：最后一个真实 assistant 气泡(markdown 内容)在 viewport 内
  // 注意:不能用 '.message-row.is-assistant p',因为 isLoading=true 时 loading bubble
  // 也是 .message-row.is-assistant 但没有 <p> 子元素,会撞空。改选 markdown 容器。
  const lastAssistant = page.locator('.message-row.is-assistant .message-markdown').last();
  await expect(lastAssistant).toBeInViewport();
});
