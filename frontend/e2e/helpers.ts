import { type Page, expect, type Locator } from '@playwright/test';

/**
 * 前端 E2E 测试共用辅助函数。
 *
 * 设计要点：
 *  - 所有选择器集中在 helpers 维护，避免散落各 spec
 *  - 等待用 Playwright 的 auto-wait，少用 waitForTimeout
 *  - 文本类断言用中文，与 UI 显示一致
 */

// 新 UI（macOS DMG desktop shell，2026-06 重构）使用以下连接状态文案：
//   - 顶部 SetupView: "本地运行已就绪"
//   - ChatView pill:  "本地在线" / "正在连接本地助手" / "本地助手离线"
//   - Sidebar 微信:   "已连接" / "未绑定"（仅微信通道）
// E2E 之前用的"已连接/未连接"是新 UI 之前的旧 ChatArea 顶部状态条，
// 已删除；helper 改用 "本地运行已就绪" 作为系统就绪指示。
const WELCOME_HEADING = '把日常想法交给一个更安静的助手';
const READY_INDICATOR = '本地运行已就绪';
export type QuickPromptTitle = '写代码' | '分析数据' | '知识问答' | '写作助手';

/** 打开首页（vite serve 在 /app/ 子路径），等待欢迎语出现，自动切到 ChatView。
 *
 * 新 desktop shell 流程：SetupView（无输入框）→ 点击"新任务"→ ChatView。
 * 把"点新任务"塞进 openHome 统一处理，spec 不再重复。
 */
export async function openHome(page: Page): Promise<void> {
  await page.goto('/app/');
  // 等待 SetupView 显示 "本地运行已就绪"（系统就绪指示）
  await expect(page.getByText(READY_INDICATOR, { exact: true })).toBeVisible({ timeout: 20_000 });
  // 等待欢迎界面标题
  await expect(page.getByRole('heading', { name: new RegExp(WELCOME_HEADING) })).toBeVisible();

  // 切到 ChatView：优先侧栏"新任务"按钮，回退欢迎页 CTA
  const sidebarNew = page.locator('button.btn-new-task');
  if (await sidebarNew.count()) {
    await sidebarNew.first().click();
  } else {
    const firstTask = page.getByRole('button', { name: '+ 新建第一个任务' });
    if (await firstTask.count()) {
      await firstTask.click();
    }
  }
}

/** 获取欢迎界面上的某个快捷 prompt 按钮。 */
export function quickPromptButton(page: Page, title: QuickPromptTitle): Locator {
  return page.getByRole('button', { name: new RegExp(`^${title}`) });
}

/** 定位输入框。
 *  - 新 UI（macOS DMG desktop shell，2026-06）："告诉 Nexus 你想完成什么"
 *  - 旧 UI（已删除）："输入消息..."
 */
export function messageInput(page: Page): Locator {
  return page.getByPlaceholder('告诉 Nexus 你想完成什么');
}

/** 定位发送按钮（textarea 后面那个 SVG 按钮，aria-label 没设，用父 div 定位）。 */
export function sendButton(page: Page): Locator {
  return page.locator('button').filter({ has: page.locator('svg path[d^="M12 19"]') });
}

/**
 * 发送一条消息并等"非流式"完成信号。
 *
 * 完整流：user 气泡 → assistant 气泡（isLoading=true → 收到 chunk → done → isLoading=false）。
 * done 事件本身不更新气泡文本，但会触发 isLoading 回到 false。
 * 我们等"loading 消失 + 助手气泡里有非空文本" 来判断完成。
 *
 * 关键：必须等 **新一条** assistant 出现且非空，不能只看"最后一个 assistant 有文本"——
 * 紧接上一条还没回完时，helper 可能拿到上一条的文本提前返回。多轮场景下这会导致
 * 总气泡数少 1（user N 已发，assistant N 还在生成中）。
 */
export async function sendMessageAndWaitForReply(
  page: Page,
  content: string,
  options: { minReplyLength?: number; timeoutMs?: number } = {},
): Promise<string> {
  const { minReplyLength = 1, timeoutMs = 60_000 } = options;

  // 发送前的 user / assistant 数量基线
  const userRowsBefore = await page.locator('.message-row.is-user').count();
  const assistantRowsBefore = await page.locator('.message-row.is-assistant').count();

  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill(content);
  await sendButton(page).click();

  // 等 user 气泡出现且数量增加 1
  await expect
    .poll(
      async () => await page.locator('.message-row.is-user').count(),
      { timeout: 5_000 },
    )
    .toBe(userRowsBefore + 1);

  // 等对应的新 assistant 行出现且非空文本——
  // 这里 "数量 >= 旧数 + 1" 是关键：避免错把上一轮已结束的 assistant 当成新的
  await expect(async () => {
    const userCount = await page.locator('.message-row.is-user').count();
    const assistantCount = await page.locator('.message-row.is-assistant').count();
    // 等待新 assistant 行已渲染
    expect(assistantCount).toBeGreaterThanOrEqual(assistantRowsBefore + 1);
    // 等 user / assistant 行数一致（最后一条 assistant 是当前这条的回复）
    expect(assistantCount).toBe(userCount);
    // 最后一条 assistant 必须有非空文本
    const reply = await lastAssistantBubbleText(page);
    expect(reply.length).toBeGreaterThanOrEqual(minReplyLength);
  }).toPass({ timeout: timeoutMs, intervals: [500, 1000, 2000] });

  // 最后等输入框重新可点（流彻底结束、loading 状态彻底清掉）
  await expect(messageInput(page)).toBeEnabled({ timeout: timeoutMs });
  return lastAssistantBubbleText(page);
}

/** 拿到页面上最后一个 assistant 气泡的纯文本。
 *  新 UI（2026-06 desktop shell）：assistant 气泡外层有 ``message-row.is-assistant`` 类。
 */
export async function lastAssistantBubbleText(page: Page): Promise<string> {
  const assistantRows = page.locator('.message-row.is-assistant p');
  const count = await assistantRows.count();
  if (count === 0) {
    return (await page.locator('main p').last().innerText().catch(() => '')).trim();
  }
  return (await assistantRows.nth(count - 1).innerText()).trim();
}

/** 拿到页面上最后一个 user 气泡的纯文本。
 *  新 UI（2026-06 desktop shell）：user 气泡外层有 ``message-row.is-user`` 类。
 *  取该类容器内的 ``<p>`` 文本。
 */
export async function lastUserBubbleText(page: Page): Promise<string> {
  const userRows = page.locator('.message-row.is-user p');
  const count = await userRows.count();
  if (count === 0) {
    // 回退：旧 UI（div.justify-end .prose）或新 UI 切错场景
    return (await page.locator('main p').first().innerText().catch(() => '')).trim();
  }
  return (await userRows.nth(count - 1).innerText()).trim();
}

/** 当前消息数（user + assistant 总和，按 main 区 .message-row 计数）。
 *  - 新 UI 一条 assistant 消息含"思考过程"+"回复"两个段落，单算 <p> 会算成 2 条；
 *    直接数 .message-row 才是 1 条 1 气泡。
 */
export async function messageCount(page: Page): Promise<number> {
  return await page.locator('main .message-row').count();
}

/** 等错误提示出现（重试按钮可见）。 */
export function errorAlert(page: Page): Locator {
  return page.locator('[role="alert"]');
}

/** 等待 WS 断线（新 UI pill 切到 "正在连接本地助手"，因为 modelName 已配）。
 *  真正的 "本地助手离线"（offline）只在 modelName 未配时出现；WS 断开但模型已配
 *  会停在 connecting 态直到重连成功或重试耗尽。
 */
export async function waitForWsDisconnected(page: Page, timeoutMs = 15_000): Promise<void> {
  await expect(
    page.getByText('正在连接本地助手', { exact: true }),
  ).toBeVisible({ timeout: timeoutMs });
}

/** 等待 WS 重新连接（新 UI pill 显示 "本地在线"）。 */
export async function waitForWsReconnected(page: Page, timeoutMs = 30_000): Promise<void> {
  await expect(page.getByText('本地在线', { exact: true })).toBeVisible({ timeout: timeoutMs });
}
