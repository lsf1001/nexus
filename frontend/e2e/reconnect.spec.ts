import { test } from '@playwright/test';
import { openHome, sendMessageAndWaitForReply, waitForWsDisconnected, waitForWsReconnected } from './helpers';

/**
 * 断线重连 E2E：
 *   1. 打开页面，WS 已连接
 *   2. 主动关闭 WS（page.evaluate → ws.close()）
 *   3. 顶部"已连接" → "未连接"
 *   4. 等前端 useWebSocket hook 自动重连
 *   5. 顶部恢复"已连接"
 *   6. 再发一条消息，验证重连后能正常收发
 *
 * 重连逻辑：useWebSocket.ts 指数退避 1s → 2s → 4s → 8s → 16s → 30s
 * 默认 baseDelay=1000，所以首次重连约 1s 后尝试。
 */
test('断线重连：WS 断开后能自动恢复并继续收发', async ({ page }) => {
  await page.addInitScript(() => {
    const currentWindow = window as unknown as {
      __nexusSockets?: WebSocket[];
      __nexusOriginalWebSocket?: typeof WebSocket;
    };
    if (currentWindow.__nexusOriginalWebSocket) return;

    const OriginalWebSocket = window.WebSocket;
    currentWindow.__nexusSockets = [];
    currentWindow.__nexusOriginalWebSocket = OriginalWebSocket;

    function CapturedWebSocket(this: unknown, url: string | URL, protocols?: string | string[]) {
      const ws = protocols === undefined ? new OriginalWebSocket(url) : new OriginalWebSocket(url, protocols);
      currentWindow.__nexusSockets?.push(ws);
      return ws;
    }

    CapturedWebSocket.prototype = OriginalWebSocket.prototype;
    CapturedWebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
    CapturedWebSocket.OPEN = OriginalWebSocket.OPEN;
    CapturedWebSocket.CLOSING = OriginalWebSocket.CLOSING;
    CapturedWebSocket.CLOSED = OriginalWebSocket.CLOSED;
    window.WebSocket = CapturedWebSocket as unknown as typeof WebSocket;
  });

  await openHome(page);

  await page.evaluate(() => {
    const currentWindow = window as unknown as { __nexusSockets?: WebSocket[] };
    for (const ws of currentWindow.__nexusSockets ?? []) {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    }
  });

  await waitForWsDisconnected(page, 15_000);
  await waitForWsReconnected(page, 30_000);

  await sendMessageAndWaitForReply(page, '重连后再发一条', { timeoutMs: 120_000 });
});
