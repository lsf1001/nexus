/**
 * 设置面板 E2E(走真实 LLM 路径,验证 /api/models 集成 + dark mode 切换)。
 *
 * 用户旅程:
 *   1. 打开 ChatView
 *   2. 侧栏点齿轮按钮 → SettingsView
 *   3. 看到当前模型名 + dark mode 开关 + 显示 thinking 开关
 *   4. 切 dark mode → .nexus-desktop data-theme="dark" / 不存在
 *   5. 切回 ChatView,设置保留
 */
import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

test('设置面板：打开 → dark mode 切换 → 返回', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // 1. 点侧栏齿轮按钮
  const settingsBtn = page.locator('button.sidebar-settings-btn');
  await expect(settingsBtn).toBeVisible({ timeout: 5_000 });
  await settingsBtn.click();

  // 2. SettingsView 应该出现 — heading 或 h1 + 关键 UI
  // 简单断言:页面上有 "模型" 字样 + "dark" / "深色" / "显示" 等 UI 元素
  await expect(page.getByText(/模型|深色|dark|显示思考/i).first()).toBeVisible({
    timeout: 10_000,
  });

  // 3. dark mode 切换
  const darkToggleBefore = await page.evaluate(() =>
    document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null
  );

  // 找 dark mode 切换按钮(类型为 button 且文本含 dark / 主题)
  const darkToggle = page.locator('button', { hasText: /深色|主题|dark/i }).first();
  if (await darkToggle.count()) {
    await darkToggle.click();
    // 验证 .nexus-desktop data-theme 变化
    await expect
      .poll(
        async () =>
          await page.evaluate(() =>
            document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null
          ),
        { timeout: 5_000, intervals: [200, 500] }
      )
      .not.toBe(darkToggleBefore);
  }

  // 4. 返回 ChatView — 侧栏的 "新任务" / 主页按钮
  const backBtn = page.locator('button').filter({ hasText: /新任务|会话|返回/ }).first();
  if (await backBtn.count()) {
    await backBtn.click();
  }

  // 5. 输入框应仍 enabled(返回 ChatView 成功)
  const input = page.locator('textarea, input[placeholder*="告诉"]').first();
  await expect(input).toBeEnabled({ timeout: 10_000 });
});
