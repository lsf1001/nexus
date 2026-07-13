/**
 * User Journey: 模型 401 兜底
 *
 * 用户故事:
 *   1. 用户配置了一个无效密钥的模型(模拟场景)
 *   2. 用户发消息 → LLM 抛 AuthenticationError
 *   3. 后端 stream_guard classify → kind=AUTH → error_code=auth → 推 error 帧
 *   4. 前端应:
 *      a. 不无限 spinner(发送按钮重新可点 / 流结束)
 *      b. 不抛 JS 错误(无 pageerror)
 *      c. 至少提示用户密钥失效(ERROR_MESSAGES.auth 文案)
 *
 * 关键约束:
 *   - mock 模式:NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=auth_401
 *   - 强制后端 mock LLM 抛 openai.AuthenticationError
 *   - mock 实现见 nexus/backend/llm/e2e_mock.py:auth_401 分支
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

  // 等 ChatView 输入框可点(说明 useBootstrap 已通过 mock LLM 检测)
  const input = page.getByPlaceholder('告诉 Nexus 你想完成什么');
  await expect(input).toBeEnabled({ timeout: 30_000 });

  // 发消息触发 mock 401
  await input.fill('测试 401');
  await page.locator('button.send-button').click();

  // 等错误反馈:输入框重新可点(loading 结束 = 流终止)
  await expect(input).toBeEnabled({ timeout: 30_000 });

  // 关键断言 1:401 后用户能继续操作(不会死锁)
  await expect(input).toBeEnabled();

  // 关键断言 2:不抛 JS 错误
  expect(pageErrors, '401 兜底路径不应抛 JS 错误').toEqual([]);

  // 关键断言 3:页面上出现"密钥无效/已过期"提示(ChatArea ERROR_MESSAGES.auth)
  //   可能在 assistant 气泡里,可能在底部 toast —— 至少应可见一处
  await expect(
    page.getByText(/密钥|API key|api_key|auth|失效|过期|配置/i).first(),
    '应至少出现一处密钥失效相关文案',
  ).toBeVisible({ timeout: 10_000 });
});
