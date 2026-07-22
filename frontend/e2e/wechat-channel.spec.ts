/**
 * 微信通道 UI E2E(不依赖真实微信扫码)。
 *
 * v1.5.4:微信入口从侧栏 footer-link + PreferencesDrawer 微信 tab
 * 改为 CommandPalette(Cmd+K)→ "打开微信通道" → WeChatModal 弹窗。
 *
 * 真实扫码依赖外部微信 server(无本地环境),此 spec 只覆盖 UI 入口 +
 * API 集成 + 弹窗渲染。
 */
import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

test('微信通道:Cmd+K 调色板 → 打开微信通道 → WeChatModal → QR 请求 → 关闭', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // 提前注册 waitForResponse(WeChatModal 打开即自动触发 fetchWechatQr,
  // 如果在 modal visible 之后才注册会 race)
  const qrReqPromise = page.waitForResponse(
    (resp) =>
      resp.url().includes('/api/channels/wechat/qr') && resp.request().method() === 'POST',
    { timeout: 30_000 }
  );

  // 1. Cmd+K 打开 CommandPalette
  await page.keyboard.press('Meta+K');
  const palette = page.locator('.command-palette');
  if (!(await palette.isVisible().catch(() => false))) {
    await page.keyboard.press('Control+K');
  }
  await expect(palette, 'CommandPalette 应打开').toBeVisible({ timeout: 10_000 });

  // 2. 点 "打开微信通道" 项
  const wechatItem = palette.locator('li.command-palette-item', { hasText: '打开微信通道' });
  await expect(wechatItem, 'CommandPalette 中应见"打开微信通道"项').toBeVisible({ timeout: 10_000 });
  await wechatItem.click();

  // 3. WeChatModal 渲染 — v1.5.4 真实结构:.wechat-plugin-modal-overlay > .wechat-modal
  const modal = page.locator('.wechat-modal');
  await expect(modal, 'WeChatModal 应可见').toBeVisible({ timeout: 15_000 });

  // 4. 看到 "获取二维码" / "刷新二维码" 按钮(默认未绑定时 WeChatModal 自动
  //    调用 fetchWechatQr,可能直接进入 qr 步骤显示"刷新二维码")
  const getQrBtn = modal.locator('button.wechat-get-qr', { hasText: '获取二维码' });
  const refreshQrBtn = modal.locator('button.wechat-get-qr', { hasText: '刷新二维码' });
  await expect(async () => {
    const either =
      (await getQrBtn.isVisible().catch(() => false)) ||
      (await refreshQrBtn.isVisible().catch(() => false));
    expect(either, '应见"获取二维码"或"刷新二维码"按钮').toBe(true);
  }).toPass({ timeout: 10_000, intervals: [200, 500] });

  // 5. 验证后端 /api/channels/wechat/qr 真的被 hit(提前注册的 promise)
  const qrResp = await qrReqPromise;
  expect(qrResp.status()).toBe(200);
  const qrBody = await qrResp.json();
  expect(qrBody.success === undefined || qrBody.success === true).toBe(true);
  expect(qrBody.qrcode_url || qrBody.qrcode || qrBody.session_key).toBeTruthy();

  // 6. 截图(保留 QR 状态证据)
  await page.screenshot({ path: 'test-results/wechat-channel-qr.png' });

  // 7. 关闭 modal — 右上角 ×(.modal-close 在 .wechat-modal-head 内)
  const closeBtn = modal.locator('button.modal-close', { hasText: '×' });
  await expect(closeBtn, '关闭按钮应可见').toBeVisible();
  await closeBtn.click();
  await expect(modal, 'WeChatModal 应隐藏').toBeHidden({ timeout: 5_000 });

  // 8. ChatArea 一直在背后(主区不卸载)
  const chatStatus = page.locator('.chat-status-bar');
  await expect(chatStatus, 'ChatArea 顶栏应仍在').toBeVisible({ timeout: 5_000 });
});