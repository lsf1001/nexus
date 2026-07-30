/**
 * 用户旅程:Composer 附件上传(点 + 按钮 / 拖拽)+ 偏好里草稿 tab 列表 / 删除。
 *
 * 设计原则:
 *   - 走 mock LLM(`NEXUS_E2E_MOCK=1 + NEXUS_E2E_SCENARIO=allow_nexus_write`),
 *     跟其它 journey-* spec 同档;真 LLM 不稳定。
 *   - 不强依赖助手回复文本(附件注入内容由后端单独 spec 覆盖,
 *     这里只验证"用户上传 → 预览条出现 → 状态翻到 uploaded" 这条 UI 路径)。
 *   - 用 ``page.setInputFiles`` 模拟文件选择 + ``page.evaluate(() => dispatchEvent)``
 *     模拟拖拽,避免依赖用户态鼠标轨迹。
 *   - 草稿 tab 测试用 localStorage 预设 + 触发 ``nexus:open-preferences`` 事件,
 *     不依赖 UI 上是否有可点的"设置"按钮(desktop shell 该按钮 aria-label 是 "设置")。
 *
 * 选择器全部基于真实 DOM:
 *   - 上传入口 → ``[data-testid="composer-file-input"]``(Composer.tsx)
 *   - 预览条   → ``.attachment-chip-name`` / ``.attachment-chip-meta``
 *   - 拖拽目标 → ``.composer``
 *   - 发送按钮 → ``button.send-button:not(.stop-button)``(helpers.sendButton)
 *   - 偏好 tab → ``#preferences-tab-drafts``(PreferencesModal.tsx)
 *   - 草稿行   → ``.drafts-row`` / ``.drafts-row-preview`` / ``.drafts-row-delete``
 */
import { test, expect } from '@playwright/test';
import { openHome, messageInput, sendButton } from '../helpers';

const MOCK = process.env.NEXUS_E2E_MOCK === '1';
const SCENARIO = process.env.NEXUS_E2E_SCENARIO;

test.skip(!MOCK, '需要 NEXUS_E2E_MOCK=1 启用 mock LLM(真 LLM 多轮顺序跑不稳定)');
test.skip(
  SCENARIO !== 'allow_nexus_write' && SCENARIO !== undefined,
  '本套件用 NEXUS_E2E_SCENARIO=allow_nexus_write(或不设)跑普通 mock 流',
);

test.describe.configure({ mode: 'serial' });

test('点 + 按钮上传附件 → 预览条 chip 出现 → 发送', async ({ page }) => {
  test.setTimeout(90_000);

  await openHome(page);

  // 用 hidden file input 直接选文件(等价于点 ComposerToolbar 的 + 按钮)
  // setInputFiles 走真实 input.files 路径,useAttachments.addFiles 立刻拿到 File 对象
  await page.setInputFiles('[data-testid="composer-file-input"]', {
    name: 'note.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('hello world'),
  });

  // 预览条 chip 出现 + 文件名正确
  const chip = page.locator('.attachment-chip-name', { hasText: 'note.txt' });
  await expect(chip).toBeVisible({ timeout: 10_000 });

  // 等待上传完成:meta 行从 "上传中…" / "排队中…" 翻转成纯大小
  // ("1 B · 上传中…" → "1 B")。notContainText 在已 uploaded 时稳过。
  await expect(page.locator('.attachment-chip-meta').first()).not.toContainText(
    /上传中|排队中/,
    { timeout: 10_000 },
  );

  // 草稿内容填一些文本让 send 按钮可点
  await messageInput(page).fill('看看这个文件');
  await sendButton(page).first().click();

  // 流结束后输入框重新可点 = 用户 + 助手两条气泡渲染完成
  await expect(messageInput(page)).toBeEnabled({ timeout: 60_000 });
  await expect(page.locator('.message-row')).toHaveCount(2, { timeout: 10_000 });
});

test('拖拽文件到 composer → 预览条 chip 出现', async ({ page }) => {
  test.setTimeout(90_000);

  await openHome(page);

  // DataTransfer 路径:useAttachments 走 dataTransfer.files,跟 setInputFiles
  // 等价。但 DOM dragenter/dragover/drop 合成在 Playwright 里需要走 JS dispatch,
  // 不然 dragover 的 preventDefault 不生效,onDrop 不会触发。
  await page.evaluate(() => {
    const dt = new DataTransfer();
    const file = new File([new Uint8Array([104, 105])], 'drag.txt', { type: 'text/plain' });
    dt.items.add(file);
    const composer = document.querySelector('.composer');
    if (!composer) throw new Error('.composer 节点未渲染(可能 Composer 未挂载)');
    composer.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt }));
    composer.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
    composer.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
  });

  // 跟上面一样等 meta 行翻转
  await expect(
    page.locator('.attachment-chip-name', { hasText: 'drag.txt' }),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('.attachment-chip-meta').first()).not.toContainText(
    /上传中|排队中/,
    { timeout: 10_000 },
  );
});

test('PreferencesModal 草稿 tab 列出草稿 + 删除', async ({ page }) => {
  test.setTimeout(60_000);

  await openHome(page);

  // 用 localStorage 直接塞草稿(避免依赖 500ms 防抖 + 切 tab 刷新时序)。
  // useDraft 的 key 格式是 ``nexus-draft-{projectId}``;当前 active 默认 'default'。
  await page.evaluate(() => {
    localStorage.setItem(
      'nexus-draft-default',
      JSON.stringify({ text: '测试草稿内容', savedAt: Date.now() }),
    );
  });

  // 打开偏好 modal:触发 DesktopShell 监听的 window 事件
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('nexus:open-preferences'));
  });

  // 切到草稿 tab
  await page.locator('#preferences-tab-drafts').click();

  // 草稿行渲染 + preview 文本正确
  const row = page.locator('.drafts-row').first();
  await expect(row).toBeVisible({ timeout: 10_000 });
  await expect(row.locator('.drafts-row-preview')).toContainText('测试草稿内容');

  // 点删除 → 列表清空
  await row.locator('.drafts-row-delete').click();
  await expect(page.locator('.drafts-row')).toHaveCount(0, { timeout: 5_000 });
  await expect(page.locator('.drafts-empty')).toBeVisible({ timeout: 5_000 });
});