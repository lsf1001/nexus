import { test, expect } from '@playwright/test';
import { openHome, sendMessageAndWaitForReply, messageCount } from './helpers';

/**
 * WS 聊天主流程 E2E：
 *   1. 打开首页（SetupView / 欢迎界面）
 *   2. 点击"新任务"进入 ChatView
 *   3. 输入并发送问题
 *   4. 收到 user 气泡 + assistant 气泡
 *   5. assistant 气泡里有非空回复
 *
 * 2026-06 适配：新 desktop shell 流程与旧 UI 不同：
 *   - 首次进入显示 SetupView（无输入框）
 *   - 需点击侧栏"新任务"或欢迎页"+ 新建第一个任务"切到 ChatView
 *   - 快捷 prompt 按钮属 DMG 阶段 2 待办，本测试暂不校验
 */
test('WS 聊天主流程：发问题收到完整回复', async ({ page }) => {
  await openHome(page);

  // 从 SetupView / 欢迎页切到 ChatView。
  // 优先点击侧栏固定"新任务"按钮（始终可见），回退到欢迎页 CTA。
  const sidebarNew = page.locator('button.btn-new-task');
  if (await sidebarNew.count()) {
    await sidebarNew.first().click();
  } else {
    await page.getByRole('button', { name: '+ 新建第一个任务' }).click();
  }

  // 发送问题
  const question = '什么是 Python？';
  const finalReply = await sendMessageAndWaitForReply(page, question);
  expect(finalReply.length).toBeGreaterThan(0);
  // 简单合理性检查：assistant 至少回答了几个字（不是空也不是单一标点）
  expect(finalReply.replace(/[\s\p{P}]/gu, '').length).toBeGreaterThan(2);

  // 当前应有 2 条气泡（user + assistant）
  const count = await messageCount(page);
  expect(count).toBeGreaterThanOrEqual(2);
});
