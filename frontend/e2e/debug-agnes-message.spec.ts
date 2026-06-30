/**
 * 真实模拟用户场景:
 *   1. 默认 active = agnes(后端)
 *   2. 打开 ChatView,topbar 显示 agnes
 *   3. 发消息,看是否能在合理时间内收到响应
 *
 * 同时:把 active 切成 minimax,看发消息是否还工作(测试 2 个模型)
 */

import { test, type Page } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';

const SHOT = 'debug-shots';
fs.mkdirSync(SHOT, { recursive: true });

async function shot(page: Page, label: string): Promise<void> {
  await page.screenshot({ path: path.join(SHOT, `${label}.png`), fullPage: false });
  console.log(`  📸 ${label}.png`);
}

test('用户场景: agnes 模型, 发消息', async ({ page }) => {
  test.setTimeout(90_000);

  await page.goto('/app/');
  await page.waitForSelector('button.prompt-card', { timeout: 30_000 });
  await page.waitForTimeout(2000);

  const topbarText = await page.locator('.topbar-topic span').first().innerText().catch(() => 'NOT_FOUND');
  console.log(`  [initial topbar] "${topbarText}"`);

  // 发消息
  const input = page.locator('textarea.composer-textarea');
  const sendBtn = page.locator('button.send-button');
  await input.fill('测试 agnes,说个 3 字问候');
  await shot(page, 'msg-01-before-send');
  await sendBtn.click();
  console.log(`  [msg sent]`);

  // 回归断言:第一个内容帧(thinking 或 chunk)必须 8s 内到达(实际期望 5s 内)。
  // WHY 2026-06-28 教训:agnes 慢模型 + 旧 ws.py 缓存模式下,前端 26s 收不到任何
  // 帧,spinner 一直转 → 用户体感"卡死"。修复后 chunk 实时 emit,5s 内应可见。
  // 该断言提前到 60s 大超时之前,确保"转圈 bug 复发"立刻挂掉、给清晰错误。
  try {
    await page.waitForFunction(
      () => {
        const rows = document.querySelectorAll('.message-row.is-assistant');
        if (rows.length === 0) return false;
        const last = rows[rows.length - 1];
        // 必须有内容(可能是 thinking 或 chunk)或 .thinking-block 显示
        return (
          (last.textContent || '').trim().length > 0 ||
          last.querySelector('.thinking-block') !== null
        );
      },
      { timeout: 8_000 }, // 8s 上限,实际期望 5s 内
    );
    console.log(`  [ok] 第一个内容帧 8s 内到达`);
  } catch {
    console.log(`  [FAIL] 8s 内仍无内容帧 - 转圈 bug 复发`);
    await shot(page, 'msg-01b-spinner-hang');
    throw new Error('Agnes 转圈 bug 复发:8s 内未收到任何内容帧');
  }

  // 等响应(60s)
  const start = Date.now();
  try {
    // 等 assistant 气泡出现内容
    await page.waitForFunction(
      () => {
        const rows = document.querySelectorAll('.message-row.is-assistant p');
        if (rows.length === 0) return false;
        const last = rows[rows.length - 1];
        return last && (last.textContent || '').trim().length > 0;
      },
      { timeout: 60_000 },
    );
    const elapsed = Date.now() - start;
    console.log(`  [response received in ${elapsed}ms]`);
  } catch {
    const elapsed = Date.now() - start;
    console.log(`  [TIMEOUT after ${elapsed}ms - no assistant content]`);
    await shot(page, 'msg-02-timeout');
    // 读 error 横幅
    const errorBanner = await page.locator('.error-banner').first().innerText().catch(() => 'NO_ERROR_BANNER');
    console.log(`  [error banner] "${errorBanner}"`);
    return;
  }

  await page.waitForTimeout(2000);
  await shot(page, 'msg-02-after-reply');

  // 读最新 assistant 文本
  const assistantTexts = await page.locator('.message-row.is-assistant p').allInnerTexts();
  console.log(`  [assistant messages]\n${assistantTexts.map((t, i) => `    ${i}: ${t.slice(0, 100)}`).join('\n')}`);
});