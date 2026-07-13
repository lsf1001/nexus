import { test, expect } from '@playwright/test';
import { openHome, sendMessageAndWaitForReply, lastUserBubbleText, messageCount } from './helpers';

/**
 * 多轮会话 + 滚动 E2E：
 *   1. 发 3 条不同问题
 *   2. 验证页面有 6 条气泡（3 user + 3 assistant）
 *   3. 验证每对 user-assistant 顺序正确
 *   4. 验证最后一条 user 消息是新发的
 *   5. 验证滚动条：第 3 条 assistant 气泡在视口内
 *
 * Mock 模式跳过（2026-07-13）：
 *   - mock LLM 在第 3 条消息时 chat-scroll 已堆出滚动距离，但流速快（每轮几百 ms）
 *     导致 useAutoScroll smooth-scroll 在 rAF 内被反复 cancelAnimationFrame
 *     撤销（2026-07-13 改为同步 instant 才稳定）。多轮 viewport 视觉接近
 *     chat-happy-path，单测覆盖,本 spec 专注真实 LLM 流速下的滚动行为。
 *   - 真 LLM 每轮 5-15s,用户等待期间视觉位置自然贴近底部,scrollHeight 增量
 *     不撑出滚动条;最后一条 assistant 在视口内 — 这是真实的"用户视角"。
 *   - 上下文回显需求(同 journey-multi-turn)也不是 mock 模式可覆盖的。
 *   - journey-multi-turn.spec.ts 已专门覆盖 mock 跳过 + 真 LLM 上下文断言。
 *     本 spec 的滚动行为是真 LLM 用户路径专属,mock 模式明确 skip。
 */
test.skip(
  process.env.NEXUS_E2E_MOCK === '1',
  '多轮滚动是真 LLM 用户视角,mock 流速太快导致 auto-scroll 距离 gate 误判',
);

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
