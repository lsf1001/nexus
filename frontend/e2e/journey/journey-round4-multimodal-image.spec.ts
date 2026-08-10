/**
 * User Journey: Round 4 T4.4 多模态图片注入 LLM 验证
 *
 * 验证链路:
 *   1. 用户从 Composer 上传 1x1 PNG 附件 → 后端 /api/attachments 落库
 *   2. 用户 send "这张图里有什么?" 携带 attachmentIds
 *   3. 后端 ws handler → sessions.build_messages_with_attachments 走 multi-part
 *      注入路径,LLM (mock) 收到 ``HumanMessage.content`` 是 list,含
 *      ``{"type": "image", "source": {"type": "base64", ...}}`` block
 *   4. Playwright 通过新加的 E2E 诊断端点 GET /api/e2e/last-messages
 *      读出 mock LLM 最后一次 _generate 的 messages,断言 user content
 *      里**至少一个** block 的 type == "image"
 *
 * 设计要点:
 *   - 与 chat-attachments.spec.ts 共用附着路径(选文件 + 等 chip + 等
 *     uploaded 状态 + 打字 + send),但断言走 mock 的 last_messages,
 *     不依赖 UI 是否显式渲染了图(前端预览是 E2E_mock 套件不覆盖的)。
 *   - 1x1 PNG base64 内联(48 bytes)避免依赖本地 fixture 文件。
 *   - 跑顺序放最后(NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=allow_nexus_write),
 *     mock 第一次 invoke 触发 write_file 到 .nexus/,HITL allow 路径。
 *   - 跨 spec 顺序跑时 mock last_messages 会被覆盖,本 spec 只
 *     看本轮 invoke 后的状态 — 所以必须放在 E2E 套件末尾,或者通过
 *     request fixture 拿到独立的 mock 实例(当前实现走全局单例,
 *     spec 顺序敏感性已记录)。
 */
import { test, expect } from '@playwright/test';
import { openHome, messageInput, sendButton } from '../helpers';

const MOCK = process.env.NEXUS_E2E_MOCK === '1';
const SCENARIO = process.env.NEXUS_E2E_SCENARIO;

test.skip(!MOCK, '需要 NEXUS_E2E_MOCK=1 启用 mock LLM(mock 唯一能捕获 _generate 入参)');
test.skip(
  SCENARIO !== 'allow_nexus_write' && SCENARIO !== undefined,
  '本套件用 NEXUS_E2E_SCENARIO=allow_nexus_write(或不设) — 避免 HITL 阻挡 send',
);

// 1×1 透明 PNG base64, 共 48 bytes
const PNG_1x1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

test('上传 PNG + 文字 → LLM 收到 image block', async ({ page }) => {
  test.setTimeout(120_000);

  await openHome(page);

  // 1. 选 PNG 文件 → chip 出现 → meta 行翻到纯大小 (跟 chat-attachments 同路径)
  await page.setInputFiles('[data-testid="composer-file-input"]', {
    name: 'pixel.png',
    mimeType: 'image/png',
    buffer: PNG_1x1,
  });
  const chip = page.locator('.attachment-chip-name', { hasText: 'pixel.png' });
  await expect(chip).toBeVisible({ timeout: 10_000 });
  // 等 meta 行从 "上传中…" / "排队中…" 翻到只剩大小
  await expect(page.locator('.attachment-chip-meta').first()).not.toContainText(
    /上传中|排队中/,
    { timeout: 10_000 },
  );

  // React state 时序:uploadOne setAttachments('uploaded') 后,Composer 闭包
  // 里 uploadedServerIds 才会过滤到 serverId。meta 翻转是同一渲染周期的
  // 视觉信号,但 handleSend 在 React 受控按钮里是 useCallback 重新绑定,
  // 给 500ms 让 useAttachments 的 useCallback 重绑定完成,避免 handleSend
  // 触发时拿到的是上一帧的 []。在本地 + CI 都偶发,加了后稳过。
  await page.waitForTimeout(500);

  // 2. 输入文本 + send
  await messageInput(page).fill('这张图里有什么?');
  await sendButton(page).first().click();

  // 等流结束 — user / assistant 双气泡 + 输入框重新可点
  await expect(messageInput(page)).toBeEnabled({ timeout: 60_000 });
  await expect(page.locator('.message-row')).toHaveCount(2, { timeout: 10_000 });

  // 3. 拉后端 /api/e2e/last-messages, 断言 user content 是 list 且含 image block。
  // 内容路径结构(user_message from MultiModalInject):
  //   HumanMessage.content = [
  //     {"type": "text", "text": "..."},
  //     {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
  //   ]
  const payload = await page.evaluate(async () => {
    const r = await fetch('/api/e2e/last-messages');
    if (!r.ok) throw new Error(`/api/e2e/last-messages returned ${r.status}`);
    return (await r.json()) as { messages: Array<{ type: string; content: unknown }> };
  });

  // 至少有一组 messages (系统 + 历史 + user 至少 3 条)
  expect(payload.messages.length).toBeGreaterThan(0);

  // 找 user 消息 — content 是 list 且含 type=image block
  const userMessage = payload.messages.find(
    (m) => m.type === 'HumanMessage',
  );
  expect(userMessage, '应至少有一条 HumanMessage').toBeTruthy();

  // content 应是 list
  expect(Array.isArray(userMessage!.content), 'HumanMessage.content 应该是 list(multi-part)').toBe(true);

  // 列表里应有 type === 'image' 的 block (Round 2 T3 图片注入实现)
  const imageBlock = (userMessage!.content as Array<{ type: string }>).find(
    (b) => b.type === 'image',
  );
  expect(imageBlock, 'HumanMessage.content 里应有 type=image block').toBeTruthy();

  // text block 也应有 — 用户的 "这张图里有什么?" 文本
  const textBlock = (userMessage!.content as Array<{ type: string; text?: string }>).find(
    (b) => b.type === 'text',
  );
  expect(textBlock, 'HumanMessage.content 里应有 type=text block').toBeTruthy();
  expect(textBlock!.text).toContain('这张图里有什么');
});
