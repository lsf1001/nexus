/**
 * User Journey: 流期间的发送按钮状态
 *
 * 用户故事(对应产品现状 — 无 stop 按钮,见 src/components/ChatArea/Composer.tsx:55):
 *   1. 发消息,assistant 开始流式输出
 *   2. 流期间发送按钮 disabled(isLoading=true),用户无法点
 *   3. 流结束后,发送按钮重新可点
 *
 * 关键约束:
 *   - 真 LLM,慢。流快慢不在 spec 关心范围内,只验证"流期间 disabled"这一
 *     关键不变量。
 *   - 当前产品没有"中途 stop"按钮(Composer.tsx:52-58,send-button 在
 *     isLoading 时直接 disabled,无 abort 通道)。本 spec 验证现有行为而非
 *     虚构 stop 功能。
 */
import { test, expect } from '@playwright/test';
import { journeyOpenHome } from './helpers';
import { messageInput, sendButton } from '../helpers';

test('流期间 send-button disabled', async ({ page }) => {
  test.setTimeout(60_000);

  await journeyOpenHome(page);

  // 1. 触发流
  await messageInput(page).fill('Python 一句话');
  await sendButton(page).click();

  // 2. 流期间断言:send-button 应 disabled
  //    (说明 click 真的触发了 send,而非 noop)
  await expect(async () => {
    const isDisabled = await sendButton(page).isDisabled();
    expect(isDisabled, '流期间 send-button 应 disabled(说明已触发流)').toBe(true);
  }).toPass({ timeout: 30_000, intervals: [500, 1000] });
});
