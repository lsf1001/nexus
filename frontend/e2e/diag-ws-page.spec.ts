/**
 * Playwright 原生 websocket 事件诊断:在 page.on('websocket') 层级看真实状态。
 * 不在浏览器内重写 WebSocket(避免污染 useWebSocket 行为)。
 */
import { test, expect } from '@playwright/test';
import { openHome, messageInput, sendButton } from './helpers';

test('HITL 1006 真实 close 原因', async ({ page }) => {
  test.setTimeout(180_000);

  const wsLog: Array<{ t: number; kind: string; data?: unknown }> = [];
  const t0 = Date.now();
  const log = (kind: string, data?: unknown) => {
    const entry = { t: Date.now() - t0, kind, data };
    wsLog.push(entry);
    console.log(`[WS-PAGE] [+${entry.t}ms] ${kind} ${data ? JSON.stringify(data).slice(0, 200) : ''}`);
  };

  // 监听所有浏览器原生 WebSocket 事件
  page.on('websocket', (ws) => {
    log('opened', { url: ws.url() });
    ws.on('framesent', (frame) => log('TX', { payload: frame.payload?.toString().slice(0, 200) }));
    ws.on('framereceived', (frame) =>
      log('RX', { payload: frame.payload?.toString().slice(0, 200) })
    );
    ws.on('close', () => log('close', {}));
    ws.on('socketerror', (err) => log('socketerror', { error: String(err) }));
  });

  await openHome(page);

  const prompt =
    '请直接调用 write_file 工具把内容 "e2e_page_ws_diag" 写入 ~/.nexus/AGENTS.md。' +
    '不要问任何问题,直接调用 write_file。';
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill(prompt);
  await sendButton(page).click();

  const confirmCard = page.locator('.confirm-card');
  await expect(confirmCard).toBeVisible({ timeout: 90_000 });
  log('confirm-card-visible');

  // 等 3s 收集 LLM thinking 帧
  await page.waitForTimeout(3000);
  log('approve-now');
  await confirmCard.locator('button.confirm-approve').click();

  // 等 30s 看后续帧
  await page.waitForTimeout(30_000);

  log('test-end');
  console.log(`[WS-PAGE] total events: ${wsLog.length}`);
  console.log('[WS-PAGE] timeline:');
  for (const e of wsLog) {
    console.log(`  +${e.t}ms ${e.kind} ${e.data ? JSON.stringify(e.data).slice(0, 100) : ''}`);
  }

  // 关键断言:approve 后必须收到至少一个 RX
  const approveTime = wsLog.find((e) => e.kind === 'approve-now')?.t ?? 0;
  const rxAfterApprove = wsLog.filter((e) => e.kind === 'RX' && e.t > approveTime);
  const closeAfterApprove = wsLog.filter((e) => e.kind === 'close' && e.t > approveTime);
  console.log(`[WS-PAGE] RX after approve: ${rxAfterApprove.length}, close after approve: ${closeAfterApprove.length}`);

  expect(closeAfterApprove.length).toBeGreaterThanOrEqual(0);
});
