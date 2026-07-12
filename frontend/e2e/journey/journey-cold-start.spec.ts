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
