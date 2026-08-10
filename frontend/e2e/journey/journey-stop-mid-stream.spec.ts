/**
 * User Journey: 流期间点 stop 按钮立即停止
 *
 * 用户故事(模拟人工):
 *   1. 发消息,assistant 开始流式输出(看见 send 按钮已变成 stop 按钮)
 *   2. 用户在流中途点 stop 按钮
 *   3. 流立即停止:
 *      - stop 按钮被 send 按钮替换(isLoading=false,input 已被 clear)
 *      - 当前 assistant 末尾出现 "[已停止]" 标记
 *      - 后续再发消息,新流正常推送(stopped gate 不残留)
 *
 * 设计决策:
 *   - 2026-07-13 新增 stop 按钮,客户端软停止(useChatStream.stoppedRef)。
 *   - 服务端 stream 仍会跑到自然结束(后端无 abort 帧),但客户端 gate 把后续
 *     chunk / thinking / final 全部丢弃,不写 store。
 *   - 视觉反馈:在最后一条 assistant 末尾追加 "已停止" marker,用户清楚知道流被切。
 *   - Mock LLM(`NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=allow_nexus_write`):mock
 *     流确定快(几百 ms 完成),适合测试 stop 按钮立即切换 + 已停止 marker 显示。
 *     真 LLM 流时长不可控,可能 mock 完成 + 后续 chunk 都被 gate 掉,marker 验证
 *     会受流速影响。
 *   - **NEXUS_E2E_MOCK_DELAY_SEC=2**(必设):让 mock 在生成前 sleep 2 秒,流持续
 *     ~2s,给 stop-button click 留出充足窗口。playwright.config.ts 已默认注入。
 *   - test.setTimeout 90s。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput, sendButton } from '../helpers';

test.skip(
  process.env.NEXUS_E2E_MOCK !== '1',
  '需要 NEXUS_E2E_MOCK=1 启用 mock LLM(stop 按钮测试需要流确定快)'
);
test.skip(
  process.env.NEXUS_E2E_SCENARIO !== 'allow_nexus_write',
  '需要 NEXUS_E2E_SCENARIO=allow_nexus_write(普通 mock 流,不触发 HITL)'
);

test('流期间点 stop 按钮', async ({ page }) => {
  test.setTimeout(90_000);

  // 2026-07-22:不再预先 fs.rm e2e_allow.md。改 e2e_mock.py 让 scenario 写到
  // $NEXUS_HOME/outputs/(Playwright 注入的隔离 /tmp/.../nexus-playwright-<pid>/),
  // 跨 spec 顺序跑时 FilesystemBackend / deepagents 模块单例不共享 → mock
  // 第一次就进 tool_calls 路径,stop-mid-stream 直接拿到流式 chunk → stop
  // 按钮可见 → [已停止] marker 命中。之前 ~50 行注释里的"reflection 路径污染"
  // 场景由 mock 改动根治。

  await journeyOpenHome(page);

  // 1. 触发流。`click({ force: true })` 跳过 Playwright 的 stability + enabled
  //    auto-wait:full suite 下 mock 流期间 React 持续重渲染(stop-button ↔ send-button
  //    反复切换),button DOM 元素永远 stable 不下来,默认 `click()` 会卡 14~36 秒,
  //    等到流结束 click 才返回,届时 stop-button 已不存在 → 测试 FAIL。`force: true`
  //    直接派发 mouse event,不 auto-wait。isolated 跑下流更"快"自然也 OK,但统一
  //    加 force 保证两套时序下都稳。
  await messageInput(page).fill('Python 一句话介绍');
  await sendButton(page).click({ force: true });

  // 2. 等 stop 按钮出现(替换 send 按钮)
  const stopButton = page.locator('button.stop-button');
  await expect(stopButton).toBeVisible({ timeout: 30_000 });

  // 3. 点 stop → setIsLoading(false) + 末尾追加 [已停止]
  //    NEXUS_E2E_MOCK_DELAY_SEC=2 让流持续 ~2s,stop-button 可见时间足够点击。
  //    用 `.click({ force: true })` 跳过 Playwright 的 stability + enabled
  //    auto-wait:mock 流期间 React 在持续 render(thinking / chunk 帧每
  //    ~50ms 让 button DOM attribute 抖动),`click({ timeout })` 默认会等
  //    "stable" 而超时;`force: true` 直接派发 mouse event,即时命中。
  await stopButton.click({ force: true });

  // 4. 验证 stop 按钮被替换为 send 按钮(isLoading=false)
  await expect(stopButton).toBeHidden({ timeout: 5_000 });
  await expect(sendButton(page)).toBeVisible({ timeout: 5_000 });

  // 5. 验证 assistant 末尾有 [已停止] 标记
  //    选择器:.message-row.is-assistant 是 ChatBubble 渲染的根元素(无 data-role 属性)
  const lastAssistant = page.locator('.message-row.is-assistant').last();
  await expect(lastAssistant).toBeVisible({ timeout: 5_000 });
  await expect(lastAssistant).toContainText('已停止', { timeout: 5_000 });

  // 6. 后续再发消息,新流能正常推进(stopped gate 已被 pushUserAndPlaceholder 清)
  await messageInput(page).fill('OK');
  await sendButton(page).click();

  // 等新一轮流启动(stop 按钮再次出现)
  await expect(stopButton).toBeVisible({ timeout: 30_000 });

  // 7. 等流自然结束(后端发 done → 前端 setIsLoading(false)):
  //    - 新一轮 assistant 至少有 2 条气泡(>=2 user + >=2 assistant)
  //    - 流结束 → isLoading=false → stop 按钮被 send 按钮替换
  //    - send 按钮此时仍 disabled(input 在发送时 clearInput,UI 行为正确,无需填新内容)
  //    - 关键:新流没被残留的 stoppedRef gate 掉(看到正常助手回复而非 "[已停止]")
  await expect(async () => {
    // 等待流结束:stop 按钮重新隐藏
    await expect(stopButton).toBeHidden({ timeout: 5_000 });
    const userCount = await page.locator('.message-row.is-user').count();
    const assistantCount = await page.locator('.message-row.is-assistant').count();
    expect(userCount, '应有 user 气泡').toBeGreaterThanOrEqual(2);
    expect(assistantCount, '应有 assistant 气泡').toBeGreaterThanOrEqual(2);
    // 第二条 assistant 是新一轮流回复 — 不应含 [已停止](说明 stopped gate 已清)
    const secondAssistant = page.locator('.message-row.is-assistant').nth(1);
    await expect(secondAssistant).not.toContainText('已停止');
  }).toPass({ timeout: 120_000, intervals: [1000, 2000, 3000] });
});