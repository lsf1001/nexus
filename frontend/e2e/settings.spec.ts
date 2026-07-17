/**
 * 偏好抽屉通用 tab E2E(走真实 LLM 路径,验证 /api/models 集成 + dark mode 切换)。
 *
 * 第十三轮(2026-07-17):原 SettingsView 全屏视图取消,统一为 PreferencesDrawer 右侧抽屉。
 *   1. 打开 ChatView
 *   2. 侧栏齿轮 → 抽屉从右滑入,默认"通用" tab
 *   3. 看到当前模型名 + dark mode 开关 + 显示 thinking 开关
 *   4. 切 dark mode → .nexus-desktop data-theme 变化
 *   5. 点 ✕ 关闭抽屉,ChatArea 一直在背后(主区不卸载)
 */
import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

test('偏好抽屉通用 tab：齿轮 → dark mode 切换 → ✕ 关闭', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // 1. 点侧栏齿轮按钮
  const settingsBtn = page.locator('button.sidebar-settings-btn');
  await expect(settingsBtn).toBeVisible({ timeout: 5_000 });
  await settingsBtn.click();

  // 2. PreferencesDrawer 抽屉应该出现 — 蒙层 + 通用 tab 自动激活
  const overlay = page.locator('.preferences-drawer-overlay');
  await expect(overlay).toBeVisible({ timeout: 10_000 });
  const generalTab = page.locator('.preferences-tab', { hasText: '通用' });
  await expect(generalTab).toHaveAttribute('aria-selected', 'true');

  // 3. 关键 UI 元素(模型 / 深色 / 显示思考)
  await expect(page.getByText(/模型|深色|dark|显示思考/i).first()).toBeVisible();

  // 4. dark mode 切换
  const darkToggleBefore = await page.evaluate(() =>
    document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null
  );

  // 找 drawer 内的 dark mode 切换按钮(限制在 overlay 范围内,避免误点其他)
  const darkToggle = overlay.locator('button', { hasText: /深色|主题|dark/i }).first();
  await expect(darkToggle).toBeVisible();
  await darkToggle.click();

  await expect
    .poll(
      async () =>
        await page.evaluate(() =>
          document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null
        ),
      { timeout: 5_000, intervals: [200, 500] }
    )
    .not.toBe(darkToggleBefore);

  // 5. 点 ✕ 关闭抽屉
  const closeBtn = page.locator('.preferences-drawer-close');
  await closeBtn.click();
  await expect(overlay).toBeHidden({ timeout: 5_000 });

  // 6. ChatArea 一直在背后(主区不卸载)— composer 仍 enabled
  const input = page.locator('textarea.composer-textarea, input[placeholder*="告诉"]').first();
  await expect(input).toBeEnabled({ timeout: 10_000 });
});