/**
 * User Journey: 快捷 prompt + 新会话 + 历史列表扩展
 *
 * 用户故事(模拟人工):
 *   1. 打开 ChatView,4 个 QUICK_PROMPTS 卡片渲染(空态)
 *   2. 点 "整理今天的待办" → 文本填入输入框 → 手动 send → assistant 回复
 *   3. Sidebar 出现 1 个会话项(server 反向 session_created 通知)
 *   4. 点 "新对话" → 输入框清空、可继续输入
 *   5. 在新会话中再发一条消息 → Sidebar 自动插入第 2 个会话项 ← 关键回归
 *
 * 设计决策:
 *   - "新对话后 sidebar 自动插入新会话项"是 2026-07-13 修复的核心场景:
 *     旧实现 backend session_id 是 server 端累积状态,onNewTask 后 client
 *     getSessionId()=null,但 server 拿到的还是上一轮的 session_id(uuid),
 *     整段创建逻辑被跳过,server 不推 session_created → frontend sidebar 不增长。
 *   - 修复(handlers.py user-message 路径)改成"每轮独立解析 session_id",
 *     新一轮 user 消息拿不到 client_supplied_id 时,服务端生成新 uuid + create_session
 *     + 发 session_created。
 *   - Mock LLM(`NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=allow_nexus_write`):mock
 *     跑得比真 LLM 快且确定,适合验证"是否 sidebar 增长"这种"会话生命周期"
 *     类断言。真 LLM 跑同一条 spec 不稳定(multi-turn 顺序跑 sidebar 计数会
 *     受前面 spec 干扰)。
 *   - Mock 模式下 first round 会触发 .nexus/outputs/e2e_allow.md 写入(HITL/permission
 *     已 allow),second round 也会触发同一写入(每次 user message 都被 mock 当成
 *     "首次进入" — 因上下文里有 allow feedback)。流结束后 sidebar 应增长到 ≥2 项。
 *   - test.setTimeout 90s(mock 比真 LLM 快很多,2 轮 ~30-50s)。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput, sendButton, messageCount } from '../helpers';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1',
  '需要 NEXUS_E2E_MOCK=1 启用 mock LLM(真 LLM 在多 spec 顺序跑时 sidebar 计数不可控)'
);
test.skip(
  process.env.NEXUS_E2E_SCENARIO !== 'allow_nexus_write',
  '需要 NEXUS_E2E_SCENARIO=allow_nexus_write(普通 mock 流,不触发 HITL 路径)'
);

test('快捷 prompt → 新会话 → sidebar 增长', async ({ page }) => {
  test.setTimeout(90_000);

  await journeyOpenHome(page);

  // 1. 4 个 QUICK_PROMPTS 渲染
  const quickPrompts = page.locator('button.prompt-card');
  await expect(quickPrompts).toHaveCount(4, { timeout: 30_000 });

  // 2. 点 "整理今天的待办" → EmptyState 把 prompt 文本填入 textarea
  const quickPrompt = quickPrompts.filter({ hasText: '整理今天的待办' });
  await expect(quickPrompt).toBeVisible({ timeout: 10_000 });
  await quickPrompt.click();
  await expect(messageInput(page)).not.toHaveValue('', { timeout: 5_000 });

  // 3. 手动发送 → 等流结束
  await sendButton(page).click();
  await expect(async () => {
    const count = await messageCount(page);
    expect(count, '应有 user + assistant 至少 2 条气泡').toBeGreaterThanOrEqual(2);
    await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });
  }).toPass({ timeout: 120_000, intervals: [1000, 2000, 3000] });

  // 4. Sidebar 至少 1 个会话项(初始会话)。用 first() 避免依赖顺序跑前序 spec 残留。
  const sidebar = page.locator('.task-item');
  await expect(sidebar.first()).toBeVisible({ timeout: 10_000 });
  const initialSidebarCount = await sidebar.count();
  console.log(`[quick-prompts] 第 1 轮后 sidebar 项数: ${initialSidebarCount}`);

  // 5. 点 "新对话" → 输入框清空、可继续输入
  await page.locator('button.btn-new-task').click();
  await expect(messageInput(page)).toHaveValue('', { timeout: 10_000 });
  await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });

  // 6. 在新会话中再发一条消息 → sidebar 应增加 1 项(核心回归断言)
  await messageInput(page).fill('Hi 第 2 个会话');
  await sendButton(page).click();
  await expect(async () => {
    const count = await messageCount(page);
    expect(count, '新会话应至少 2 条气泡').toBeGreaterThanOrEqual(2);
    await expect(messageInput(page)).toBeEnabled({ timeout: 5_000 });
  }).toPass({ timeout: 120_000, intervals: [1000, 2000, 3000] });

  // 关键断言:sidebar 必须有 >= 2 项 — 修复前这里 regression 失败
  await expect(async () => {
    const finalCount = await sidebar.count();
    console.log(`[quick-prompts] 第 2 轮后 sidebar 项数: ${finalCount}`);
    expect(
      finalCount,
      `新会话后 sidebar 应至少 ${initialSidebarCount + 1} 项,实际 ${finalCount}`
    ).toBeGreaterThanOrEqual(initialSidebarCount + 1);
  }).toPass({ timeout: 15_000, intervals: [500, 1000, 2000] });
});