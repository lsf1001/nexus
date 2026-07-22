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

  // 澄清问题应作为 assistant 消息显示,用户选择"烧烤"应作为 user 消息显示。
  // 注:mock WS 推 done 帧后不再发 chunk,assistant 气泡可能只渲染占位,
  // 不强制要求 markdown 非空 — 这一点由真实 LLM 链路(non-mock E2E)覆盖。
  await expect(page.locator('.message-row.is-assistant', { hasText: '今天想吃什么?' })).toBeVisible();
  await expect(page.locator('.message-row.is-user', { hasText: '烧烤' })).toBeVisible();
});

// ============== 2. 自由输入流程 ==============


test('澄清流程：无候选项时显示兜底候选 + 自定义回答', async ({ page }) => {
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

  // v1.5.4 兜底 UX:options 为空时组件塞 2 个 fallback 按钮(让 Nexus 帮我想 /
  // 我需要更多信息)+ 一个"自己写回答"折叠区,避免面对空白输入框发懵。
  // 原 spec 断言 "options 不应出现"已不成立 — 验证 fallback 按钮可见即可。
  await expect(clarifyCard.getByRole('button', { name: '让 Nexus 帮我想' })).toBeVisible();
  await expect(clarifyCard.getByRole('button', { name: '我需要更多信息' })).toBeVisible();

  // 自由输入路径:展开 <details> 后 textarea 应可见且可输入。
  // 注意:这是兜底分支,没有 autoFocus / onKeyDown(Enter 不直接提交);
  // 用户必须先展开折叠区 → 填文本 → 点"发送"按钮。
  await clarifyCard.locator('summary', { hasText: '自己写回答' }).click();
  const textarea = clarifyCard.locator('textarea.clarify-textarea');
  await expect(textarea).toBeVisible();
  await textarea.fill('我想说的是天气');

  const submitBtn = clarifyCard.getByRole('button', { name: '发送' });
  await expect(submitBtn).toBeEnabled();
  await submitBtn.click();

  // 验证 send 被调用
  const payload = await lastSentPayload(page);
  expect(payload).not.toBeNull();
  expect(payload?.content).toBe('我想说的是天气');

  // 表单消失
  await expect(clarifyCard).toBeHidden({ timeout: 2_000 });
});

// ============== 3. 取消流程 ==============


test('澄清流程：兜底候选按钮点击提交 + 表单清除', async ({ page }) => {
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

  // v1.5.4 兜底分支(options=[])不渲染"取消"按钮,改测 fallback 按钮点击提交:
  // 点"我需要更多信息" → 应触发 send(content=按钮文本)并清表单。
  const fallbackBtn = clarifyCard.getByRole('button', { name: '我需要更多信息' });
  await expect(fallbackBtn).toBeVisible();
  await fallbackBtn.click();

  // 验证 send 被调用 + 内容是按钮文本
  const payload = await lastSentPayload(page);
  expect(payload).not.toBeNull();
  expect(payload?.content).toBe('我需要更多信息');

  // 验证表单消失
  await expect(clarifyCard).toBeHidden({ timeout: 2_000 });
});
