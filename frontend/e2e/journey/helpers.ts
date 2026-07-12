/**
 * journey 专用高层动作封装。
 *
 * 与 e2e/helpers.ts 的边界:
 *  - e2e/helpers.ts 偏底层(locator / 单次 send / 一次重连):单个选择器或单步动作。
 *  - 本文件偏 journey 层:连发多条 / 触发 HITL 卡片 / kill backend / 验上下文回显
 *    这种"模拟用户一段操作"的封装。
 *
 * 设计原则:
 *  - 所有函数接受 Playwright Page 作为第一参数,无全局状态。
 *  - 失败抛 Error,带上下文(哪段 journey / 哪条消息),便于 debug。
 *  - 不复用现有 e2e/helpers.ts 的内部函数,只 import 公开 API(openHome / sendMessageAndWaitForReply
 *    / messageInput / sendButton / messageCount),避免循环依赖和耦合。
 */
import { type Page, expect, type Locator } from '@playwright/test';
import {
  openHome,
  sendMessageAndWaitForReply,
  messageInput,
  sendButton,
  messageCount,
  lastAssistantBubbleText,
} from '../helpers';

/** journey-cold-start / multi-turn 共用的"打开 ChatView"入口(转发到 e2e/helpers.ts.openHome) */
export async function journeyOpenHome(page: Page): Promise<void> {
  await openHome(page);
}

/** 多轮发送:连发多条,等所有回复到位,返回各条 assistant 回复文本数组 */
export async function sendSequence(
  page: Page,
  contents: string[],
  options: { perMessageTimeoutMs?: number } = {},
): Promise<string[]> {
  const { perMessageTimeoutMs = 120_000 } = options;
  const replies: string[] = [];
  for (const content of contents) {
    const reply = await sendMessageAndWaitForReply(page, content, {
      timeoutMs: perMessageTimeoutMs,
    });
    replies.push(reply);
  }
  return replies;
}

/** 上下文回显断言:最后一条 assistant 文本包含所有 keywords */
export async function expectContextRecall(
  page: Page,
  keywords: string[],
): Promise<void> {
  const lastText = await lastAssistantBubbleText(page);
  for (const kw of keywords) {
    expect(lastText, `期望最后一条 assistant 回复含关键词 "${kw}", 实际: ${lastText}`).toContain(kw);
  }
}

/** HITL 卡片定位(与 e2e/hitl-confirm.spec.ts:82 一致) */
export function hitlConfirmCard(page: Page): Locator {
  return page.locator('.confirm-card');
}

/** HITL 批准按钮定位(与 hitl-confirm.spec.ts:86 一致)。
 *  拒绝按钮 selector 在实施时按需从源码 grep 确认(本 plan 不预定义,避免死代码)。
 */
export function hitlApproveButton(page: Page): Locator {
  return page.locator('.confirm-card button.confirm-approve');
}

/** 后端进程是否还活着(/health 200) */
export async function isBackendAlive(page: Page): Promise<boolean> {
  // 通过浏览器 fetch 后端 /health,避免直连端口(可能与 webServer 配置不一致)
  try {
    const resp = await page.evaluate(async () => {
      const r = await fetch('http://127.0.0.1:30000/health');
      return r.status;
    });
    return resp === 200;
  } catch {
    return false;
  }
}

/**
 * 杀后端:用 pkill -f uvicorn.nexus.backend.main:app
 *
 * Playwright 启动的 webServer 在 CI(reuseExistingServer=false)杀完后会
 * 自动重启;本地 dev(reuseExistingServer=true)杀完后端会污染后续 spec,
 * 跑前需设 NEXUS_E2E_RESILIENCE=1 或单独跑。
 */
export async function killBackend(): Promise<void> {
  const { spawn } = await import('node:child_process');
  await new Promise<void>((resolve, reject) => {
    const proc = spawn('pkill', ['-f', 'uvicorn.nexus.backend.main:app'], {
      stdio: 'pipe',
    });
    proc.on('exit', (code) => {
      // pkill 退码: 0 = killed >=1, 1 = no proc matched
      if (code === 0 || code === 1) resolve();
      else reject(new Error(`pkill exit ${code}`));
    });
    proc.on('error', reject);
  });
}

/** 等后端 /health 200,timeout 30s */
export async function waitBackendAlive(page: Page, timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isBackendAlive(page)) return;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Backend /health 未在 ${timeoutMs}ms 内恢复`);
}
