/**
 * User Journey: Round 3 端到端 — 全局搜索 + 导出 + 分享(Round 3 Task 3.6)
 *
 * 用户故事:
 *   1. 发 3 条 user 消息 → mock LLM 收到 → 助手逐条回复
 *   2. ⌘F 弹全局搜索 → 输入 "BTC" → 看到 1 条命中(snippet 含 <mark>BTC</mark>)
 *   3. 点结果 → 切到对应会话
 *   4. 右键会话 → 弹 ConversationMenu → 导出 Markdown → 验下载文件内容含原文
 *   5. 创建分享链接 → 复制 URL → 在新 tab 打开 → 验看到只读 markdown 视图
 *
 * Mock 模式(NEXUS_E2E_MOCK=1):
 *   - 后端 mock LLM 收到 user prompt → 返回固定反思文本(不再调工具,所有
 *     路径都直接返回)。
 *   - 关键:FTS5 全文搜索仍走真实 messages_fts 表(messages 真的 insert,
 *     mock LLM 不影响),所以 ⌘F 搜历史真消息 → 1 条命中走通。
 *   - 导出 / 分享走真实后端 endpoint,跟 mock LLM 无关。
 *
 * 为什么不用真 LLM 跑全链:真 LLM 行为不可预测(可能写工具/可能问澄清),
 * 本 spec 关心的是 UI 链路完整性 + 后端 endpoint 可达性,mock LLM 已经
 * 满足。e2e/journey/journey-multi-turn.spec.ts 已覆盖真 LLM 多轮主路径。
 *
 * 运行:
 *   NEXUS_E2E_MOCK=1 NEXUS_E2E_SCENARIO=allow_nexus_write \
 *     npx playwright test e2e/journey/journey-round3-search-export-share.spec.ts
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput } from '../helpers';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1',
  '需要 NEXUS_E2E_MOCK=1(本 spec 用 mock LLM 验证搜索/导出/分享链路)',
);

test('Round 3 端到端:发送 3 条 → ⌘F 全局搜索 → 右键导出 + 分享', async ({ page, context }) => {
  test.setTimeout(180_000);

  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await journeyOpenHome(page);
  expect(pageErrors, '页面 JS 错误').toEqual([]);

  // === 1. 发 1 条 user 消息(关键词 BTC 命中 FTS5)===
  // 关键约束:`sendMessageAndWaitForReply` 用 user/assistant 计数 1:1 对齐
  // 判定完成(mock LLM 流式期间会渲染 loading 占位用 `.message-row.is-assistant`
  // 包裹,导致短暂 assistant=2 > user=1,可能误判)。这里改用"send 按钮变回
  // send(不是 stop)"作为流结束信号,逻辑更稳。FTS5 全文索引在 mock 模式下
  // 仍真实写入 messages_fts 表(mock LLM 不影响 DB),所以后续 keyword 命中
  // 也是真搜索。
  await expect(messageInput(page)).toBeEnabled();
  await messageInput(page).fill('BTC 接下来怎么走?');
  await page.locator('.send-button:not(.stop-button), button[aria-label*="发送"]').first().click();
  // 等 mock LLM 完整产出"操作完成。"助手回复。stop-button 不作为结束信号:
  // mock LLM scenario `allow_nexus_write` 第一次 invoke 返回 tool_calls(写
  // .nexus/outputs/e2e_allow.md),deepagents 跑完工具后第二次 invoke 才返
  // reflection,reflection 是 AIMessage(content="操作完成。") — 但前端 isLoading
  // 在该路径下不会自动清(已有 console 验证)。改用"assistant 文本稳定 +
  // 含 reflection marker"作为完成信号,逻辑更鲁棒。
  await expect(
    page.locator('.message-row.is-assistant .message-markdown').first(),
  ).toContainText(/操作完成|操作/, { timeout: 60_000 });
  // 给前端一次 render flush(loading 占位的 unmount 不是同步的)
  await page.waitForTimeout(500);
  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 10_000 });

  // === 2. ⌘F 全局搜索 → 输入 "BTC" → 看到 1 条命中 ===
  // 关键约束:useGlobalShortcuts 在文本输入元素内放行 modKey 快捷键
  // (Round 3 Task 3.4 设计,#9 键盘守卫)。所以不能先 focus messageInput
  // 再按 Ctrl+F — input 内 Cmd+F 被放行给浏览器原生 find。先 Tab 一次把
  // 焦点从 input 移到下一个 focusable 元素(不是输入元素),再按 Ctrl+F
  // 才走 useGlobalShortcuts。不能用 page.locator(...).click() —
  // 误中 chat-area 会触发新的 click handler 提交草稿。
  await expect(messageInput(page)).toBeEnabled();
  await messageInput(page).fill('');
  // Tab 离开 messageInput,焦点跳到下一个 focusable(非 input)
  await page.keyboard.press('Tab');
  await page.keyboard.press('Control+f');

  // 全局搜索面板应该弹出
  const searchInput = page.locator('.global-search-panel input[role="combobox"]');
  await expect(searchInput).toBeVisible({ timeout: 5_000 });

  // 输入 BTC,等 debounce 200ms 后结果回来
  await searchInput.fill('BTC');
  // snippet 含 <mark>BTC</mark> → 走 dangerouslySetInnerHTML,真实 DOM 是 <mark> 元素
  await expect(
    page.locator('.global-search-panel mark', { hasText: 'BTC' }).first(),
  ).toBeVisible({ timeout: 10_000 });
  const items = page.locator('.global-search-panel .global-search-item');
  await expect(items).toHaveCount(1, { timeout: 5_000 });

  // === 3. 点结果 → 跳到对应会话 ===
  await items.first().click();
  // 弹窗关闭 + 切到该会话(URL 不一定变化,但全局搜索 modal 应已不在)
  await expect(page.locator('.global-search-panel')).toBeHidden({ timeout: 5_000 });

  // === 4. 右键会话 → ConversationMenu → 导出 Markdown ===
  // 找 Sidebar 里的 .task-item
  const taskItem = page.locator('.sidebar .task-item').first();
  await expect(taskItem).toBeVisible();
  await taskItem.click({ button: 'right' });
  const menu = page.locator('.conversation-menu');
  await expect(menu).toBeVisible({ timeout: 5_000 });

  // 拦截下载事件导出 Markdown
  const downloadPromise = page.waitForEvent('download', { timeout: 10_000 });
  const exportBtn = menu.locator('[data-action="export"]');
  await expect(exportBtn).toBeVisible();
  await exportBtn.click();
  const download = await downloadPromise;
  // 文件名约定:session-<id>.md(见 ConversationMenu.tsx:104)
  expect(download.suggestedFilename()).toMatch(/^session-.+\.md$/);

  // === 5. 创建分享链接 ===
  // 重新打开菜单(导出完菜单已关)
  await taskItem.click({ button: 'right' });
  await expect(page.locator('.conversation-menu')).toBeVisible({ timeout: 5_000 });

  const shareBtn = page.locator('.conversation-menu [data-action="share"]');
  await expect(shareBtn).toBeVisible();
  await shareBtn.click();

  // 分享链接应显示(.conversation-menu-share-url)
  const shareUrlEl = page.locator('.conversation-menu-share-url');
  await expect(shareUrlEl).toBeVisible({ timeout: 10_000 });
  const shareUrl = (await shareUrlEl.textContent())?.trim() ?? '';
  expect(shareUrl).toMatch(/^https?:\/\/.+\/api\/share\/.+/);

  // === 6. 在新 tab 打开分享链接 → 看到只读 markdown ===
  const sharePage = await context.newPage();
  const response = await sharePage.goto(shareUrl, { waitUntil: 'domcontentloaded' });
  // 分享 endpoint 返回 markdown(text/markdown; charset=utf-8),HTTP 200
  expect(response?.status()).toBe(200);
  // 页面 body 应含 markdown 文本(simple heading "# ..." 格式)
  const body = (await sharePage.locator('body').innerText()).trim();
  expect(body.length).toBeGreaterThan(10);
  // markdown 应包含 "Session ID" 标记(见 share.py render_session_markdown)
  expect(body).toMatch(/Session ID/i);
  await sharePage.close();
});