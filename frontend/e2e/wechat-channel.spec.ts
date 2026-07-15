/**
 * 微信通道 UI E2E(不依赖真实微信扫码)。
 *
 * 用户旅程:
 *   1. 打开 ChatView
 *   2. 侧栏点 "微信通道" → WechatAssistantView
 *   3. 看到绑定状态卡("未绑定"文案) + "扫码绑定"按钮
 *   4. 点"扫码绑定" → WechatPluginModal 打开
 *   5. modal 内点 "绑定微信" → 触发 /api/channels/wechat/qr 拿到 QR
 *   6. 关闭 modal,返回 WechatAssistantView
 *
 * 真实扫码依赖外部微信 server(无本地环境),此 spec 只覆盖 UI 入口 + API 集成 + 弹窗渲染。
 */
import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

test('微信通道：侧栏入口 → 绑定弹窗 → QR 请求', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // 1. 侧栏微信通道链接存在
  const wechatLink = page.locator('button.footer-link--wechat');
  await expect(wechatLink).toBeVisible({ timeout: 10_000 });
  const linkText = (await wechatLink.innerText()).trim();
  expect(linkText).toContain('微信通道');

  // 2. 点击进入 WechatAssistantView
  await wechatLink.click();
  // 关键 UI 文案出现 → view 已切到 wechat
  await expect(page.getByText('微信通道是 Nexus 的随身入口。')).toBeVisible({
    timeout: 10_000,
  });

  // 3. 看到 "扫码绑定 / 重新绑定" 按钮(.wechat-extra-actions 是 wechat-view 子树内)
  const bindBtn = page
    .locator('.wechat-extra-actions button.btn-primary', { hasText: '扫码绑定' })
    .first();
  await expect(bindBtn).toBeVisible({ timeout: 5_000 });

  // 4. 点击触发 WechatPluginModal
  await bindBtn.click();

  // modal 渲染(背景: 微信插件 + 绑定微信 按钮)
  const modal = page.locator('div.fixed.inset-0').filter({ hasText: '微信插件' });
  await expect(modal).toBeVisible({ timeout: 10_000 });
  const innerBindBtn = modal.locator('button', { hasText: '绑定微信' });
  await expect(innerBindBtn).toBeVisible({ timeout: 5_000 });

  // 5. 点 "绑定微信" 触发 /api/channels/wechat/qr → 应展示 QR canvas
  // 监听 QR 请求,验证后端 API 真的被 hit
  const qrReqPromise = page.waitForResponse(
    (resp) =>
      resp.url().includes('/api/channels/wechat/qr') && resp.request().method() === 'POST',
    { timeout: 10_000 }
  );
  await innerBindBtn.click();
  const qrResp = await qrReqPromise;
  expect(qrResp.status()).toBe(200);
  const qrBody = await qrResp.json();
  expect(qrBody.qrcode_url || qrBody.qrcode).toBeTruthy();

  // QR canvas 渲染(进入 qr 步骤)
  await expect(modal.locator('canvas')).toBeVisible({ timeout: 5_000 });
  await expect(modal.getByText('等待扫码')).toBeVisible();

  // 截图(保留 QR 状态证据)
  await page.screenshot({ path: 'test-results/wechat-channel-qr.png' });

  // 6. 关闭 modal — 右上角 ×
  const closeBtn = modal.locator('button').filter({ has: page.locator('svg') }).first();
  await closeBtn.click();
  await expect(modal).toBeHidden({ timeout: 5_000 });

  // 7. 返回 chat 入口还在(第八轮 2026-07-15:返回按钮现在是
  //   chat-status-bar 内的 .chat-status-action,不再是绝对定位的 .back-btn)
  const backBtn = page.locator('button.chat-status-action', { hasText: '返回聊天' });
  if (await backBtn.count()) {
    await backBtn.click();
    await expect(wechatLink).toBeVisible({ timeout: 5_000 });
  }
});
