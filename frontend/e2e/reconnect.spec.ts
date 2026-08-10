import { test, expect } from '@playwright/test';
import { openHome, lastAssistantBubbleText, messageInput, sendButton } from './helpers';

/**
 * 断线重连 E2E：
 *   1. 打开页面，业务 WS 已连接（捕获在 __nexusAppSockets[0]）
 *   2. 主动关闭该 WS
 *   3. 等待 useWebSocket 指数退避（1s）后重建新 WS
 *   4. 验证 __nexusAppSockets 出现新条目
 *   5. 新 WS 进入 OPEN 状态
 *   6. 再发一条消息，验证重连后能正常收发
 *
 * 设计权衡：
 *  - Vite HMR 也会在浏览器里建一个 `ws://host/app/?token=...`，
 *    自带重连。如果测试捕获所有 WebSocket，关闭时会一起关掉，
 *    Vite 重连会污染 `__nexusSockets` 数组 → 无法判定业务 WS 是否真的重连。
 *  - 因此 init script 只 push 业务 WS（URL 包含 `/api/ws` 但不是 Vite HMR），
 *    Vite HMR 不进 `__nexusAppSockets`。
 *  - 2026-07-12 WS 鉴权改造回归:旧匹配 `/api/ws?` 在 token 改走 subprotocol
 *    后失效(URL 无 `?`)。改为只匹配 `/api/ws` + 排除 `vite-hmr` 子协议。
 *    Vite HMR 在 dev 模式总是建 `ws://host/app/?token=...`(URL 带 `?token=`,
 *    subprotocol `vite-hmr`),业务 WS 没 `?token=`、subprotocol `nxv1-<b64u>`。
 *  - 不再用 UI 文案 "本地在线" 断言：2026-06 macOS DMG 新 UI 在 WS
 *    connecting 状态时 pill 显示 "正在连接本地助手"，但具体文案易变；
 *    走编程式 WS 数组断言更稳定。
 *
 * 重连逻辑：useWebSocket.ts 指数退避 1s → 2s → 4s → 8s → 16s → 30s
 * 默认 baseDelay=1000，首次重连约 1s 后尝试。
 */
const APP_WS_KEY = '__nexusAppSockets';

test('断线重连：WS 断开后能自动恢复并继续收发', async ({ page }) => {
  await page.addInitScript((key) => {
    const w = window as unknown as {
      [k: string]: unknown;
    };
    const OriginalWebSocket = window.WebSocket;
    // 避免 hot reload / page reload 重置数组——如果 addInitScript 重跑，
    // 已有 entries 应保留（否则测试中段 navigate 会丢历史）。
    if (!w[key as keyof typeof w]) {
      (w as Record<string, unknown>)[key] = [];
    }
    if (w.__nexusOriginalWebSocket) return;
    w.__nexusOriginalWebSocket = OriginalWebSocket;

    function CapturedWebSocket(this: unknown, url: string | URL, protocols?: string | string[]) {
      const urlStr = String(url);
      const ws =
        protocols === undefined
          ? new OriginalWebSocket(url)
          : new OriginalWebSocket(url, protocols);
      // 只收 Nexus 业务 WS(/api/ws),Vite HMR(/app/?token=...)不进。
      // 2026-07-12 WS 鉴权改造后 token 走 Sec-WebSocket-Protocol,业务 URL
      // 不再带 `?token=`;Vite HMR dev 总是 `ws://host/app/?token=...`。
      // 旧 `/api/ws?` 匹配在 token 改走后失效(URL 无 `?`)。
      if (urlStr.includes('/api/ws') && !urlStr.includes('?token=')) {
        const arr = (w[key as keyof typeof w] as WebSocket[] | undefined) ?? [];
        arr.push(ws);
      }
      return ws;
    }

    CapturedWebSocket.prototype = OriginalWebSocket.prototype;
    CapturedWebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
    CapturedWebSocket.OPEN = OriginalWebSocket.OPEN;
    CapturedWebSocket.CLOSING = OriginalWebSocket.CLOSING;
    CapturedWebSocket.CLOSED = OriginalWebSocket.CLOSED;
    window.WebSocket = CapturedWebSocket as unknown as typeof WebSocket;
  }, APP_WS_KEY);

  await openHome(page);

  const initialSockets = await page.evaluate((key) => {
    const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
    return arr.length;
  }, APP_WS_KEY);
  expect(initialSockets).toBeGreaterThanOrEqual(1);

  // 关闭业务 WS——走非正常关闭(code=1006,wasClean=false)模拟网络断开,
  // WsClient 的 wasClean 检测逻辑(code=1000 不重连)才会进入退避重连路径。
  // WHY:Playwright 直接 ws.close() 默认 code=1000 正常 FIN,服务端 1000
  // 响应,wasClean=true,WsClient 见 wasClean 就放弃 reconnect。
  await page.evaluate((key) => {
    const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
    for (const ws of arr) {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        // dispatchEvent 模拟异常断网(1006 abnormal closure)。不调 ws.close():
        // 它默认 1000 会让 WsClient 误判 wasClean=true 而不重连。
        const ev = new CloseEvent('close', { code: 1006, reason: 'abnormal', wasClean: false });
        ws.dispatchEvent(ev);
      }
    }
  }, APP_WS_KEY);

  // 等 useWebSocket 退避后创建新 WS：__nexusAppSockets 数量应 > initialSockets
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          return arr.length;
        }, APP_WS_KEY),
      { timeout: 15_000, intervals: [200, 500, 1000, 2000] },
    )
    .toBeGreaterThan(initialSockets);

  // 最后一个 socket 应进入 OPEN 状态
  await expect
    .poll(
      async () =>
        await page.evaluate((key) => {
          const arr = (window as unknown as Record<string, WebSocket[] | undefined>)[key] ?? [];
          const last = arr[arr.length - 1];
          return last ? last.readyState : -1;
        }, APP_WS_KEY),
      { timeout: 15_000, intervals: [200, 500, 1000, 2000] },
    )
    .toBe(WebSocket.OPEN);

  // 重连后能正常收发:输入 + 发送 + 等助手有非空反应。
  // 不复用通用 helper 的 "user/assistant 行数相等"断言:真实 LLM 见"重连后再发一条"
  // 语义模糊会走 clarification panel(assistant 同时有"思考"+"回复"两行,
  // group "AI 正在向你确认")。这里只验证助手有非空反应即可。
  const input = messageInput(page);
  await expect(input).toBeEnabled({ timeout: 30_000 });
  await input.fill('重连后再发一条');
  await sendButton(page).first().click();

  await expect(async () => {
    const reply = await lastAssistantBubbleText(page);
    expect(reply.length).toBeGreaterThan(0);
  }).toPass({ timeout: 120_000, intervals: [500, 1000, 2000, 4000] });
});
