/**
 * User Journey: 网络中断与重连
 *
 * 用户故事:
 *   1. 用户正常聊天,业务 WS 已连接
 *   2. 后端进程被 kill(模拟崩溃)
 *   3. 浏览器侧 WS 断开(useWebSocket 触发重连退避)
 *   4. 重启后端,浏览器自动重连成功(WS OPEN)
 *   5. 用户能继续发问并收到回复
 *
 * 实施注意:
 *   - 本 spec 在 CI 必跑(Playwright webServer 杀完会自动重启)。
 *   - 本地 dev 模式 reuseExistingServer=true,杀完后端会污染后续 spec。
 *     跑前需设 NEXUS_E2E_RESILIENCE=1 或单独跑。
 *   - 复用 e2e/reconnect.spec.ts 的 __nexusAppSockets 编程式断言 idiom,比 UI 文案稳定。
 */
import { test, expect } from '@playwright/test';
import {
  journeyOpenHome,
  killBackend,
  waitBackendAlive,
} from './helpers';
import { sendMessageAndWaitForReply } from '../helpers';

const APP_WS_KEY = '__nexusAppSockets';

// 本地 dev 模式(reuseExistingServer=true)Playwright 不会自动重启被杀的
// backend,本 spec 无法在本地跑(浏览器无限 reconnect 但后端永远不在)。
// 留 CI-only;本地用 e2e/reconnect.spec.ts 测 WS 重连(无后端重启场景)。
test.skip(
  !process.env.CI,
  '需要 CI 环境(Playwright webServer 自动重启被杀的 backend)',
);

test('重连稳态:后端 kill → 重启 → 浏览器自动恢复并继续对话', async ({ page }) => {
  test.setTimeout(240_000);

  // 复用 reconnect.spec.ts 的 WS 捕获模式
  await page.addInitScript((key) => {
    const w = window as unknown as Record<string, unknown>;
    const OriginalWebSocket = window.WebSocket;
    if (!w[key]) w[key] = [];
    if (w.__nexusOriginalWebSocket) return;
    w.__nexusOriginalWebSocket = OriginalWebSocket;
    function CapturedWebSocket(this: unknown, url: string | URL, protocols?: string | string[]) {
      const urlStr = String(url);
      const ws =
        protocols === undefined
          ? new OriginalWebSocket(url)
          : new OriginalWebSocket(url, protocols);
      if (urlStr.includes('/api/ws')) {
        const arr = (w[key] as WebSocket[] | undefined) ?? [];
        arr.push(ws);
      }
      return ws;
    }
    CapturedWebSocket.prototype = OriginalWebSocket.prototype;
    Object.assign(CapturedWebSocket, {
      CONNECTING: OriginalWebSocket.CONNECTING,
      OPEN: OriginalWebSocket.OPEN,
      CLOSING: OriginalWebSocket.CLOSING,
      CLOSED: OriginalWebSocket.CLOSED,
    });
    window.WebSocket = CapturedWebSocket as unknown as typeof WebSocket;
  }, APP_WS_KEY);

  await journeyOpenHome(page);

  // 初始应有 1+ 个业务 WS
  const initialCount = await page.evaluate((key) => {
    const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
    return arr.length;
  }, APP_WS_KEY);
  expect(initialCount).toBeGreaterThanOrEqual(1);

  // 杀后端
  await killBackend();

  // 等浏览器感知到后端死(SIGKILL 后 TCP RST/timeout,browser readyState → CLOSED)
  // 走 wasClean=false 才会让 WsClient 进入退避重连路径。
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          return arr.length > 0 ? arr[arr.length - 1].readyState : -1;
        }, APP_WS_KEY),
      { timeout: 15_000, intervals: [200, 500, 1000] },
    )
    .toBe(3 /* WebSocket.CLOSED */);

  // 等新 WS(自动重连,可能需要 1-30s 退避)
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          return arr.length;
        }, APP_WS_KEY),
      { timeout: 60_000, intervals: [1_000, 2_000, 3_000, 5_000] },
    )
    .toBeGreaterThan(initialCount);

  // 等后端重启成功(给 Playwright webServer 自动重启时间)
  await waitBackendAlive(page, 30_000);

  // 等新 WS 进入 OPEN 状态
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          const last = arr[arr.length - 1];
          return last ? last.readyState : -1;
        }, APP_WS_KEY),
      { timeout: 30_000, intervals: [1_000, 2_000, 3_000] },
    )
    .toBe(1 /* WebSocket.OPEN */);

  // 重连后能正常收发
  await sendMessageAndWaitForReply(page, '重连后再发一条', { timeoutMs: 120_000 });
});