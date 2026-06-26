import { test, expect } from '@playwright/test';
import { openHome, messageInput, sendButton } from './helpers';

/**
 * HITL 确认卡片 E2E(真实 LLM)。
 *
 * 用户旅程:
 *   1. 在 ChatView 输入框要求 AI 写一个文件
 *   2. LLM 触发 FilesystemPermission interrupt,后端发 confirmation_request
 *   3. 前端 .confirm-card 出现,带 [批准] [拒绝] 两个按钮
 *   4. 模拟用户点 [批准]
 *   5. 流继续 → 收到 final 文本,流结束
 *   6. 验证输入框重新可点 + 卡片消失
 *
 * 真实 LLM 路径,会跑 1-2 分钟。
 */
test('HITL 确认卡片：触发 → 批准 → 流完成', async ({ page }) => {
  test.setTimeout(180_000);

  // === 抓包:把浏览器收到的所有 WS 帧 dump 到 console ===
  // 不仅在最后 dump 一次,每帧都打 log(用 page console 转发),这样
  // 失败前也能看到流状态。
  page.on('console', (msg) => {
    const text = msg.text();
    if (text.startsWith('[WS-DEBUG]')) {
      console.log(text);
    }
  });
  await page.addInitScript(() => {
    const w = window as unknown as { __wsFrames: unknown[]; __origWS: typeof WebSocket };
    w.__wsFrames = [];
    const OrigWS = window.WebSocket;
    w.__origWS = OrigWS;
    // @ts-expect-error - 替换 WebSocket 构造器来拦截
    window.WebSocket = class extends OrigWS {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        const sock = this as unknown as WebSocket;
        const capture = (label: string) => (ev: Event) => {
          try {
            const data = (ev as MessageEvent).data;
            const parsed = typeof data === 'string' ? data : '<binary>';
            (w.__wsFrames as string[]).push(`[${label}] ${parsed}`);
            // 实时把每帧打到 page console,Playwright 通过 page.on('console')
            // 收集到 reporter。失败前的帧也能看到。
            // eslint-disable-next-line no-console
            console.log(`[WS-DEBUG] [${label}] ${parsed.slice(0, 200)}`);
          } catch {
            /* ignore */
          }
        };
        sock.addEventListener('message', capture('RX'));
        sock.addEventListener('open', () => {
          // eslint-disable-next-line no-console
          console.log(`[WS-DEBUG] [OPEN] ${url}`);
        });
        sock.addEventListener('close', (ev) => {
          // eslint-disable-next-line no-console
          console.log(`[WS-DEBUG] [CLOSE] code=${ev.code} reason=${ev.reason}`);
        });
        const origSend = sock.send.bind(sock);
        sock.send = (data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
          try {
            (w.__wsFrames as string[]).push(
              `[TX] ${typeof data === 'string' ? data : '<binary>'}`
            );
            // eslint-disable-next-line no-console
            console.log(`[WS-DEBUG] [TX] ${typeof data === 'string' ? data.slice(0, 200) : '<binary>'}`);
          } catch {
            /* ignore */
          }
          return origSend(data);
        };
      }
    };
  });

  await openHome(page);

  // 触发 AGENTS.md 写入 — 受保护路径会触发 HITL interrupt
  // 提示词故意明确:写哪个文件、什么内容,减少 LLM 试探/循环次数
  //
  // 注:真实 LLM 行为不稳定 — 有时直接动手调工具,有时用文字描述"我会用
  // write_file 写..."而不真正调。这里用更强的"必须"措辞 + 指定 tool name,
  // 配合每次 LLM 调用前补 1 轮"再试一次必须调工具"的兜底。
  //
  // 关键防 ask_user:LLM 经常问"会覆盖怎么办 / 是否确认",用 ask_user
  // 工具(不是 write_file)把决策推回用户。明确说"不要问任何问题 / 不要
  // 用 ask_user / 直接覆盖"强制走 write_file 路径触发 HITL。
  const prompt =
    '请直接调用 write_file 工具把内容 "e2e_hitl_marker_2026" 写入文件 ' +
    '~/.nexus/AGENTS.md(覆盖整个文件,只写这一行内容即可)。' +
    '不要用 ask_user 工具提问,不要用 read_file 读,不要用 ls 列目录,' +
    '不要用文字描述"我会用..."而不真调工具,直接调用 write_file 一次完成。';
  await expect(messageInput(page)).toBeEnabled({ timeout: 30_000 });
  await messageInput(page).fill(prompt);
  await sendButton(page).click();

  // 等 user 气泡出现
  await expect(page.locator('.message-row.is-user')).toHaveCount(1, { timeout: 10_000 });

  // 等确认卡片出现(.confirm-card),LLM 思考 + interrupt 桥接最慢 60s
  const confirmCard = page.locator('.confirm-card');
  await expect(confirmCard).toBeVisible({ timeout: 90_000 });

  // 卡片里至少有一个 [批准] 按钮
  const approveBtn = confirmCard.locator('button.confirm-approve');
  await expect(approveBtn).toBeVisible({ timeout: 5_000 });
  const approveText = (await approveBtn.innerText()).trim();
  expect(approveText.length).toBeGreaterThan(0);

  // 截图(保留卡片样式证据)
  await page.screenshot({ path: 'test-results/hitl-confirm-01-card.png' });

  // 用户点批准
  await approveBtn.click();

  // 卡片应当消失
  await expect(confirmCard).toBeHidden({ timeout: 5_000 });

  // 流继续:输入框重新可点(流最终结束)
  await expect(messageInput(page)).toBeEnabled({ timeout: 90_000 });

  // 至少有一个 assistant 气泡(LLM 写完文件后会有反思文本或 final)
  const assistantBubbles = page.locator('.message-row.is-assistant');
  await expect(assistantBubbles.first()).toBeVisible({ timeout: 5_000 });
  const count = await assistantBubbles.count();

  // BUG 复现:批准后 LLM 反思/final 文本应当至少有一个非空 assistant 气泡
  // 截图 02 显示完全空白 → 至少要看到一个气泡有文字内容
  const allAssistantTexts = await assistantBubbles.allInnerTexts();
  const nonEmptyCount = allAssistantTexts.filter((t) => t.trim().length > 0).length;

  await page.screenshot({ path: 'test-results/hitl-confirm-02-after-approve.png' });

  // 把诊断信息打出来,方便排查
  const frames = await page.evaluate(() => (window as unknown as { __wsFrames: unknown[] }).__wsFrames);
  console.log(`[hitl-confirm] assistant bubble count=${count}, non-empty=${nonEmptyCount}`);
  console.log(`[hitl-confirm] all assistant texts:`, JSON.stringify(allAssistantTexts, null, 2));
  console.log(`[hitl-confirm] ws frame count=${(frames as unknown[]).length}`);
  console.log(`[hitl-confirm] ws frames:\n${(frames as string[]).join('\n')}`);

  expect(nonEmptyCount).toBeGreaterThan(0);

  // bug #58 回归断言:Judge 输出(raw JSON 风格)不能出现在用户可见的 assistant 气泡里。
  // 修复前 Judge LLM 的 on_chat_model_stream 事件冒泡到 astream_events,被 ws.py 累加到
  // full_response,导致 final 帧 content 是 "{\"score\": 1.0, \"reasoning\": ...}".
  // 现在虽然 nonEmptyCount > 0,但内容必须是 LLM 的反思,不能是 Judge JSON.
  const judgeLeakInAssistant = allAssistantTexts.some(
    (t) => t.includes('"score"') || t.includes('"reasoning"') || t.includes('"evidence"')
  );
  expect(judgeLeakInAssistant).toBe(false);
});
