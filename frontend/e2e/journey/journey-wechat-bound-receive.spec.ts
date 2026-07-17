/**
 * journey-wechat-bound-receive — 微信通道"绑定状态切换"降级版 E2E。
 *
 * 覆盖范围(plan 2026-07-12-e2e-journey-suite.md Task 15 降级版):
 *  - ChatView → sidebar 微信通道入口 → PreferencesDrawer 微信通道 tab
 *    (第十三轮 2026-07-17:从原 WechatAssistantView 全屏视图改为右侧抽屉)
 *  - ChannelViewBase 初始显示"未绑定" + "扫码绑定 wechat" 按钮
 *  - mock `/api/channels/wechat/bind` GET 返回 {bound: true, account_id}
 *    → ChannelViewBase 轮询拿到新状态 → "已绑定: xxx" + 解绑按钮出现
 *
 * 为什么只有"绑定状态切换"半段(plan 降级原则):
 *  - 真实扫码流要打 ilink bot 服务,CI 没法稳定触发
 *  - 后端没有标准 inbound 端点接收微信消息推送(依赖内部协议)
 *  - mock 整个 bind 状态接口足以验证前端绑卡组件的反应性,
 *    收消息半段(消息回流 → 桌面端 inbox)留待后续 ilink sandbox 就绪后补
 *
 * 2026-07-14
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';

test.describe('journey: 微信通道绑定状态切换', () => {
  test('mock /api/channels/wechat/bind → ChannelViewBase 从未绑定切到已绑定', async ({ page }) => {
    // 1. 打开 home + mock 微信绑定接口
    await journeyOpenHome(page);

    // route 必须放在 page.goto 之前,否则首屏 useChannelStatusPolling
    // 已经拿到真实的 {bound: false},后续轮询再覆盖会有 3s 延迟。
    // 但 journeyOpenHome 已经 goto 完成,所以用 fulfill 顺序上无所谓:
    // 第一帧真实数据(未绑定)能正常显示,后续轮询(3s 一次)被 route 接管
    // 切换到 mock 的已绑定状态。
    await page.route('**/api/channels/wechat/bind', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          bound: true,
          account_id: 'e2e-mock-wx-user',
          status: 'running',
        }),
      });
    });

    // 2. sidebar 微信入口 → PreferencesDrawer 自动落微信通道 tab
    const wechatEntry = page.locator('.footer-link--wechat');
    await expect(wechatEntry, 'sidebar 微信通道入口应存在').toBeVisible();
    await wechatEntry.click();

    // 3. PreferencesDrawer 渲染,ChannelViewBase 在微信通道 tab 内
    const overlay = page.locator('.preferences-drawer-overlay');
    await expect(overlay, '偏好抽屉应打开').toBeVisible({ timeout: 10_000 });
    const wechatTab = overlay.locator('.preferences-tab', { hasText: '微信通道' });
    await expect(wechatTab, '微信通道 tab 应自动激活').toHaveAttribute('aria-selected', 'true');
    const bindCard = overlay.locator('.channel-bind-card');
    await expect(bindCard, '绑定卡片应可见').toBeVisible({ timeout: 10_000 });

    // 4. 等轮询触发 mock,绑定卡切换到"已绑定: e2e-mock-wx-user"
    // ChannelViewBase 的 useChannelStatusPolling 是 3s 一次,两次轮询
    // (首屏 + 3s 后) = ~3s 即可。给 15s 防止 CI 慢。
    await expect(bindCard).toContainText('已绑定: e2e-mock-wx-user', { timeout: 15_000 });
    await expect(bindCard.getByRole('button', { name: '解绑' })).toBeVisible();

    // 5. sidebar 状态文案同步切换(DesktopShell 把 status.bound 映射到
    //    wechatConnected,sidebar footer-link 文本从"未绑定"切到"已连接")
    await expect(wechatEntry, 'sidebar 文案应反映已连接').toContainText('已连接', {
      timeout: 5_000,
    });
    await expect(wechatEntry).toHaveClass(/is-connected/);
  });
});