/**
 * 偏好弹窗通用 tab E2E(走真实 LLM 路径,验证 dark mode + 字号 radio)。
 *
 * v1.5.4:PreferencesDrawer 右侧抽屉已被 PreferencesModal 居中模态取代。
 *   1. 打开 ChatView
 *   2. 侧栏"设置"按钮 → 模态出现(默认停在 §1 PROVIDER)
 *   3. 切到"界面"区,看到深色模式 toggle + 字号 radio
 *   4. 切深色模式 → .nexus-desktop data-theme 变化
 *   5. 点字号"大" radio → --fs 写入生效
 *   6. 点 ✕ 关闭模态,ChatArea 仍在背后(主区不卸载)
 *
 * selector 约定(2026-07-21 校对):
 *   - 侧栏设置按钮:button.settings-trigger[aria-label="设置"]
 *   - 模态 overlay:.preferences-modal-overlay
 *   - 模态 dialog:.preferences-modal[role="dialog"][aria-modal="true"]
 *   - 关闭按钮:button.preferences-modal-close[aria-label="关闭设置"]
 *   - 关闭图标:svg × close(在 preferences-modal-header 顶部右上)
 *   - 区段容器:.settings-section
 *   - 区段标题:.settings-section-title (含 PROVIDER / 界面 / 关于)
 *   - 深色 toggle:button.setting-toggle[title="深色模式"]
 *   - 字号 radio:div.radio-group[aria-label="字号"] > button[role="radio"]
 */
import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

test('偏好弹窗：侧栏"设置"按钮 → 深色模式 toggle + 字号 radio → ✕ 关闭', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // 1. 点侧栏"设置"按钮(v1.5.4:.settings-trigger + aria-label="设置")
  const settingsBtn = page.locator('button.settings-trigger[aria-label="设置"]');
  await expect(settingsBtn, '侧栏底部应见"设置"按钮').toBeVisible({ timeout: 5_000 });
  await settingsBtn.click();

  // 2. PreferencesModal 模态出现 — 居中 overlay + dialog
  const overlay = page.locator('.preferences-modal-overlay');
  await expect(overlay, 'PreferencesModal 模态应出现').toBeVisible({ timeout: 10_000 });
  const dialog = overlay.locator('.preferences-modal[role="dialog"][aria-modal="true"]');
  await expect(dialog, '对话框 role=dialog aria-modal=true').toBeVisible();

  // 3. 关键 UI 元素:章节标题 + 接口区
  //    (v1.5.4 已无 tab,改认 §1 PROVIDER / §2 界面 / §3 关于 三个区段)
  await expect(
    dialog.locator('.settings-section-title', { hasText: 'PROVIDER' }),
    '应见 §1 PROVIDER 区段',
  ).toBeVisible();
  await expect(
    dialog.locator('.settings-section-title', { hasText: '界面' }),
    '应见 §2 界面 区段',
  ).toBeVisible();

  // 4. dark mode toggle(§2 界面 → title="深色模式" 唯一锁定;按钮内只有 svg,
  //    实际文字在兄弟 .setting-row-label 的 span 里,toggle 本身不含文字节点)
  const before = await page.evaluate(
    () => document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null,
  );

  const darkToggleByTitle = dialog.locator('button.setting-toggle[title="深色模式"]');
  await expect(darkToggleByTitle, 'title=深色模式 的 toggle 应锁定唯一').toHaveCount(1);
  await expect(darkToggleByTitle, '应见深色模式 toggle').toBeVisible();
  await darkToggleByTitle.click();

  await expect
    .poll(
      async () =>
        await page.evaluate(
          () => document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null,
        ),
      { timeout: 5_000, intervals: [200, 500] },
    )
    .not.toBe(before);

  // 5. 字号 radio(小 / 中 / 大),默认选中"中",点"大"切换
  const radioGroup = dialog.locator('div.radio-group[aria-label="字号"]');
  await expect(radioGroup, '应见字号 radio-group').toBeVisible();
  const radios = radioGroup.locator('button[role="radio"]');
  await expect(radios, '应有 3 个 radio(小 / 中 / 大)').toHaveCount(3);

  // 默认选中"中"
  await expect(radios.nth(1), '默认字号 radio 应选中"中"').toHaveAttribute(
    'aria-checked',
    'true',
  );

  // 点"大" radio
  const largeRadio = radios.nth(2);
  await largeRadio.click();
  await expect(largeRadio, '点中"大" radio 应被勾选').toHaveAttribute('aria-checked', 'true');

  // 字号档位变化不影响 data-theme
  const afterFontChange = await page.evaluate(
    () => document.querySelector('.nexus-desktop')?.getAttribute('data-theme') ?? null,
  );
  expect(afterFontChange, '字号切换不应破坏 data-theme 状态').not.toBe(before);

  // 6. ✕ 关闭模态 — 在 .preferences-modal-header 右上
  const closeBtn = dialog.locator('button.preferences-modal-close[aria-label="关闭设置"]');
  await expect(closeBtn, '关闭按钮应可见').toBeVisible();
  await closeBtn.click();
  await expect(overlay, 'PreferencesModal 应消失').toBeHidden({ timeout: 5_000 });

  // 7. ChatArea 一直在背后(主区不卸载)— composer 仍 enabled
  const input = page.locator('textarea.composer-textarea, input[placeholder*="告诉"]').first();
  await expect(input, '底部 composer 应仍 enabled').toBeEnabled({ timeout: 10_000 });
});
