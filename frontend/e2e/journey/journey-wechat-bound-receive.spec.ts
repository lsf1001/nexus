/**
 * journey-wechat-bound-receive — 微信通道"绑定状态切换"降级版 E2E。
 *
 * v1.5.4:微信入口改走 CommandPalette → WeChatModal 弹窗(取代侧栏
 * footer-link + PreferencesDrawer 微信 tab)。
 *
 * 覆盖范围(plan 2026-07-12-e2e-journey-suite.md Task 15 降级版):
 *  - ChatView → Cmd+K 调色板 → "打开微信通道" → WeChatModal
 *  - mock `/api/channels/wechat/bind` GET 返回 {bound: true}
 *    → WeChatModal refreshBind() 拿到已绑定 → 显示 .wechat-connected
 *    + "解除绑定" 按钮(.wechat-unbind)
 *
 * 为什么只有"绑定状态切换"半段(plan 降级原则):
 *  - 真实扫码流要打 ilink bot 服务,CI 没法稳定触发
 *  - 后端没有标准 inbound 端点接收微信消息推送(依赖内部协议)
 *  - mock 整个 bind 状态接口足以验证前端绑卡组件的反应性,
 *    收消息半段(消息回流 → 桌面端 inbox)留待后续 ilink sandbox 就绪后补
 *
 * 2026-07-21:迁到 CommandPalette + WeChatModal(原 PreferencesDrawer 路径已删)。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';

test.describe('journey: 微信通道绑定状态切换', () => {
  test('mock /api/channels/wechat/bind → WeChatModal 从未绑定切到已绑定', async ({ page }) => {
    // 1. 打开 home + mock 微信绑定接口
    await journeyOpenHome(page);

    // route 必须放在 modal 打开之前,否则 WeChatModal 的 refreshBind 已先
    // 拿到真实 {bound: false},后续重新进 modal 才会触发新请求。
    await page.route('**/api/channels/wechat/bind', async (route) => {
      // GET 是查询 bind 状态(WeChatModal.refreshBind)
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            bound: true,
            account_id: 'e2e-mock-wx-user',
            status: 'running',
          }),
        });
        return;
      }
      // POST / DELETE 透传(让其它接口走真实后端,不影响本 test 关注点)
      await route.continue();
    });

    // 2. Cmd+K 调色板 → "打开微信通道" → WeChatModal
    await page.keyboard.press('Meta+K');
    const palette = page.locator('.command-palette');
    if (!(await palette.isVisible().catch(() => false))) {
      await page.keyboard.press('Control+K');
    }
    await expect(palette, 'CommandPalette 应打开').toBeVisible({ timeout: 10_000 });
    const wechatItem = palette.locator('li.command-palette-item', { hasText: '打开微信通道' });
    await expect(wechatItem, '应见"打开微信通道"项').toBeVisible();
    await wechatItem.click();

    // 3. WeChatModal 渲染
    const modal = page.locator('.wechat-modal');
    await expect(modal, 'WeChatModal 应可见').toBeVisible({ timeout: 15_000 });

    // 4. mock /bind 返回 bound:true → modal 应显示 .wechat-connected
    //    包含"微信已连接"文案 + 解除绑定按钮(.wechat-unbind)
    const connectedArea = modal.locator('.wechat-connected');
    await expect(connectedArea, '已绑定区应可见').toBeVisible({ timeout: 15_000 });
    await expect(connectedArea, '应见"微信已连接"文案').toContainText('微信已连接');

    const unbindBtn = modal.locator('button.wechat-unbind', { hasText: '解除绑定' });
    await expect(unbindBtn, '解除绑定按钮应可见').toBeVisible();

    // 5. 关闭 modal 验证 cleanup
    const closeBtn = modal.locator('button.modal-close', { hasText: '×' });
    await closeBtn.click();
    await expect(modal, 'WeChatModal 应隐藏').toBeHidden({ timeout: 5_000 });
  });
});