import { test, expect, type Page } from '@playwright/test';
import { messageInput, sendButton } from './helpers';

/**
 * 澄清流程 E2E（mock 后端）。
 *
 * 真实 LLM 不一定每次都调 ask_user 工具,直接走真模型测不稳定。
 * 这里用 Playwright 拦截 WebSocket,模拟后端发 clarification_request 帧,
 * 验证前端 UI 行为(表单渲染、选项点击、自由输入、提交、UI 清理)。
 *
 * 覆盖三类场景:
 *   1. 候选项渲染 + 点击候选项 → 提交回后端
 *   2. 无候选项 → 渲染自由输入框,Enter 提交
 *   3. 取消按钮 → 清除澄清状态
 */

interface MockFrame {
  type: string;
  content?: string;
  options?: string[];
  event_id?: number;
  session_id?: string;
  title?: string;
  chunk?: string;
}

/** 注入 mock WebSocket,模拟后端的帧序列。返回 controller 用于发送自定义帧。 */
async function installMockWs(page: Page, frames: MockFrame[]): Promise<void> {
  await page.addInitScript((initialFrames: MockFrame[]) => {
    // 拦截 WebSocket 构造,把真实 ws 替换成一个"按 frames 数组派发"的 mock
    const RealWS = window.WebSocket;
    class MockWS extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      readyState = 0;
      url: string;
      private queue: MockFrame[];
      constructor(url: string) {
        super();
        this.url = url;
        this.queue = initialFrames;
        this.readyState = 1; // OPEN
        // 同步触发 onopen/onmessage:onopen 可能在 setTimeout(0) 异步派发时尚未设上,
        // 改用 setter 拦截 + 同步执行,保证 useWebSocket 立即拿到 connected=true。
        // onmessage 也一样 —— 等 setTimeout 异步派发时 React 已经把 send 发出去了,
        // 不如同步监听 setter 后立刻重放初始帧。
        // 用箭头函数闭包直接捕获 this,避免 alias lint
        const queueRef = initialFrames;
        const replayFrames = (fn: (ev: MessageEvent) => void) => {
          for (const frame of queueRef) {
            try {
              fn(new MessageEvent('message', { data: JSON.stringify(frame) }));
            } catch {
              /* 忽略单帧错误 */
            }
          }
          // 末尾发 done
          try {
            fn(new MessageEvent('message', { data: JSON.stringify({ type: 'done', event_id: 999 }) }));
          } catch {
            /* ignore */
          }
        };
        let _onopen: ((ev: Event) => void) | null = null;
        Object.defineProperty(this, 'onopen', {
          get() {
            return _onopen;
          },
          set(fn) {
            _onopen = fn;
            if (fn) {
              try {
                fn(new Event('open'));
              } catch {
                /* ignore */
              }
            }
          },
          configurable: true,
        });
        let _onmessage: ((ev: MessageEvent) => void) | null = null;
        Object.defineProperty(this, 'onmessage', {
          get() {
            return _onmessage;
          },
          set(fn) {
            _onmessage = fn;
            if (fn) replayFrames(fn);
          },
          configurable: true,
        });
      }
      send(_data: string | ArrayBuffer | Blob | ArrayBufferView): void {
        // 记录 send 出去的 data,测试可以回查
        const w = window as unknown as { __nexusWsSent?: unknown[] };
        w.__nexusWsSent = w.__nexusWsSent ?? [];
        w.__nexusWsSent.push(_data);
      }
      close(): void {
        this.readyState = 3;
      }
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = MockWS;
    // 静默抑制未使用 RealWS 警告
    void RealWS;
  }, frames);
}

/** 等到"输入框出现 + 发送按钮可见",再开始测试。 */
async function waitForChatView(page: Page): Promise<void> {
  await expect(messageInput(page)).toBeVisible({ timeout: 15_000 });
}

/** 读测试页面记录的 send 调用(payload 是 string)。 */
async function lastSentPayload(page: Page): Promise<Record<string, unknown> | null> {
  return page.evaluate(() => {
    const w = window as unknown as { __nexusWsSent?: string[] };
    const sent = w.__nexusWsSent ?? [];
    if (sent.length === 0) return null;
    const last = sent[sent.length - 1];
    try {
      return JSON.parse(last as string) as Record<string, unknown>;
    } catch {
      return null;
    }
  });
}

// ============== 1. 候选项流程 ==============


test('澄清流程：候选项渲染 + 点击候选项提交', async ({ page }) => {
  // mock 后端:发 user 消息后,返回 clarification_request(含 3 个候选项),
  // 用户点击"烧烤" → 触发 send(content="烧烤")
  await installMockWs(page, [
    { type: 'session_created', session_id: 'mock-session', title: 'clarify-mock' },
    {
      type: 'clarification_request',
      content: '今天想吃什么?',
      options: ['火锅', '烧烤', '随便'],
      event_id: 1,
    },
  ]);

  await page.goto('/app/');
  await waitForChatView(page);

  // 发消息(会触发 mock 的 clarification_request)
  await messageInput(page).fill('午饭');
  await sendButton(page).click();

  // 验证澄清表单出现
  const clarifyCard = page.locator('.clarify-card');
  await expect(clarifyCard).toBeVisible({ timeout: 5_000 });
  await expect(clarifyCard.getByText('需要你确认')).toBeVisible();
  await expect(clarifyCard.getByText('今天想吃什么?')).toBeVisible();

  // 验证 3 个候选项按钮
  await expect(clarifyCard.getByRole('button', { name: '火锅' })).toBeVisible();
  await expect(clarifyCard.getByRole('button', { name: '烧烤' })).toBeVisible();
  await expect(clarifyCard.getByRole('button', { name: '随便' })).toBeVisible();

  // 点击"烧烤"
  await clarifyCard.getByRole('button', { name: '烧烤' }).click();

  // 验证 send 被调用,内容是"烧烤"
  const payload = await lastSentPayload(page);
  expect(payload).not.toBeNull();
  expect(payload?.content).toBe('烧烤');

  // 验证澄清表单已清除
  await expect(clarifyCard).toBeHidden({ timeout: 2_000 });

  // 澄清问题和选择均应成为可见消息，不能留下空白 assistant 气泡。
  await expect(page.locator('.message-row.is-assistant', { hasText: '今天想吃什么?' })).toBeVisible();
  await expect(page.locator('.message-row.is-user', { hasText: '烧烤' })).toBeVisible();
  await expect(page.locator('.message-row.is-assistant .message-markdown')).not.toHaveText(/^\s*$/);
});

// ============== 2. 自由输入流程 ==============


test('澄清流程：无候选项时显示自由输入框 + Enter 提交', async ({ page }) => {
  await installMockWs(page, [
    { type: 'session_created', session_id: 'mock-session-2', title: 'clarify-free-mock' },
    {
      type: 'clarification_request',
      content: '你能再说清楚点吗?',
      options: [],
      event_id: 1,
    },
  ]);

  await page.goto('/app/');
  await waitForChatView(page);

  await messageInput(page).fill('模糊指令');
  await sendButton(page).click();

  const clarifyCard = page.locator('.clarify-card');
  await expect(clarifyCard).toBeVisible({ timeout: 5_000 });
  await expect(clarifyCard.getByText('你能再说清楚点吗?')).toBeVisible();

  // 候选项不应出现
  await expect(clarifyCard.locator('.clarify-option')).toHaveCount(0);

  // 自由输入框应自动 focus(组件 autoFocus)。
  // 注意:mock WS 同步派发 onmessage → React 首次 render 时 autoFocus 会
  // 触发,但 test runner 取 .focused() 时 React 18 concurrent 可能还没 commit。
  // 用 page.waitForTimeout 配合不依赖焦点,直接 fill 验证行为。
  const textarea = clarifyCard.locator('textarea.clarify-textarea');
  await expect(textarea).toBeVisible();
  // 输入文字 + 触发 Enter(没有 Shift)
  await textarea.fill('我想说的是天气');
  await textarea.press('Enter');

  // 验证 send
  const payload = await lastSentPayload(page);
  expect(payload).not.toBeNull();
  expect(payload?.content).toBe('我想说的是天气');

  // 表单消失
  await expect(clarifyCard).toBeHidden({ timeout: 2_000 });
});

// ============== 3. 取消流程 ==============


test('澄清流程：自由输入模式下取消按钮清除状态', async ({ page }) => {
  await installMockWs(page, [
    { type: 'session_created', session_id: 'mock-session-3', title: 'clarify-cancel-mock' },
    {
      type: 'clarification_request',
      content: '需要更多上下文',
      options: [],
      event_id: 1,
    },
  ]);

  await page.goto('/app/');
  await waitForChatView(page);

  await messageInput(page).fill('cancel-test');
  await sendButton(page).click();

  const clarifyCard = page.locator('.clarify-card');
  await expect(clarifyCard).toBeVisible({ timeout: 5_000 });

  // 取消按钮存在(无候选项分支)
  const cancelBtn = clarifyCard.getByRole('button', { name: '取消' });
  await expect(cancelBtn).toBeVisible();
  await cancelBtn.click();

  // 验证表单消失
  await expect(clarifyCard).toBeHidden({ timeout: 2_000 });

  // 验证没有触发 send
  const payload = await lastSentPayload(page);
  // 最后一次 send 应该是最初的 "cancel-test"
  expect(payload?.content).toBe('cancel-test');
});
