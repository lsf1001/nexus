import { test, expect } from '@playwright/test';
import { openHome } from './helpers';

/**
 * WS 鉴权子协议 E2E(2026-07 改造)。
 *
 * 验证点:
 *   1. 浏览器 WS URL **不含** ?token=,token 改走 Sec-WebSocket-Protocol subprotocol
 *   2. 实际发出的 subprotocol 包含 nxv1-<base64url(token)>(2026-07-12 改前缀,
 *      旧 `nexus-v1.token=<value>` 含 `.` / `=` 违反 RFC 7230 §3.2.6 token ABNF,
 *      Chromium ≥149 抛 SyntaxError,见 git log 2026-07-12 修复)
 *   3. 旧 query 风格不被使用 → 代理 access log 不会记录 token
 *
 * 设计:
 *   - 跟 reconnect.spec.ts 一样,只收业务 WS(`/api/ws` 路径)。
 *   - 在 init script 里读 `new WebSocket(url, protocols)` 的第二个参数,
 *     并通过 `__nexusAppSocketProtocols` 暴露给测试断言。
 *   - 测试在 mock 模式 + 真 LLM 模式都跑(mock 也走真 ws,只是模型替身)。
 *
 * 不验证:token 值是否正确 — 这是后端鉴权逻辑(pytest 覆盖);E2E 只验证
 * "前端按协议发送,不进 URL"。
 */

const APP_WS_KEY = '__nexusAppSockets';
const APP_WS_PROTOCOLS_KEY = '__nexusAppSocketProtocols';

test('WS 鉴权走 Sec-WebSocket-Protocol 子协议,token 不进 URL', async ({ page }) => {
  await page.addInitScript((args: { socketsKey: string; protocolsKey: string }) => {
    const { socketsKey, protocolsKey } = args;
    const w = window as unknown as { [k: string]: unknown };
    const OriginalWebSocket = window.WebSocket;
    if (!w[socketsKey]) {
      (w as Record<string, unknown>)[socketsKey] = [];
    }
    if (!w[protocolsKey]) {
      (w as Record<string, unknown>)[protocolsKey] = [];
    }
    if (w.__nexusOriginalWebSocket) return;
    w.__nexusOriginalWebSocket = OriginalWebSocket;

    function CapturedWebSocket(
      this: unknown,
      url: string | URL,
      protocols?: string | string[],
    ) {
      const urlStr = String(url);
      const ws =
        protocols === undefined
          ? new OriginalWebSocket(url)
          : new OriginalWebSocket(url, protocols);
      // 只收 Nexus 业务 WS(/api/ws);Vite HMR(/app/)不进。
      if (urlStr.includes('/api/ws')) {
        const sockets = (w[socketsKey] as WebSocket[] | undefined) ?? [];
        sockets.push(ws);
        const protos = (w[protocolsKey] as string[][] | undefined) ?? [];
        protos.push(Array.isArray(protocols) ? protocols : protocols ? [protocols] : []);
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
  }, { socketsKey: APP_WS_KEY, protocolsKey: APP_WS_PROTOCOLS_KEY });

  await openHome(page);

  // 给 ws 一点时间 connect。
  await page.waitForFunction(
    (key: string) =>
      ((window as unknown as Record<string, unknown[]>)[key] ?? []).length > 0,
    APP_WS_KEY,
    { timeout: 10_000 },
  );

  const sockets = await page.evaluate(
    (key: string) =>
      ((window as unknown as Record<string, unknown[]>)[key] ?? []).map(
        (s) => (s as WebSocket).url,
      ),
    APP_WS_KEY,
  );
  const protocols = await page.evaluate(
    (key: string) =>
      (window as unknown as Record<string, string[][]>)[key] ?? [],
    APP_WS_PROTOCOLS_KEY,
  );

  // 至少一个业务 WS
  expect(sockets.length).toBeGreaterThan(0);
  // 业务 WS URL 不应包含 ?token=,验证 token 改造彻底。
  for (const url of sockets) {
    expect(url, `WS URL 不应包含 ?token=: ${url}`).not.toContain('?token=');
    expect(url).toContain('/api/ws');
  }

  // 至少一个 WS 用了 nxv1- 前缀的子协议(token 经 base64url 编码,见 useWsConnection.ts)。
  const hasSubprotocol = protocols.some(
    (protos) =>
      Array.isArray(protos) &&
      protos.some((p) => typeof p === 'string' && p.startsWith('nxv1-')),
  );
  expect(hasSubprotocol, '业务 WS 应通过 Sec-WebSocket-Protocol 子协议传递 token').toBe(true);
});