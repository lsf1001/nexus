import { test, expect, type Page } from '@playwright/test';
import { openHome, messageInput, sendButton } from './helpers';

/**
 * REJECT 拒答显示 E2E（mock 后端）。
 *
 * 为什么不打真实 LLM：
 *   - 真实 LLM 对"Zorgon 算法"这种诱导幻觉的问题,有时候会认真写长文
 *     (它真以为这是某种加密算法),有时会拒答,180s 内行为不可预测。
 *   - 旧版真实 LLM 版 flakey rate 约 30%(在 commit 7ea9cbe 实测 best-effort)。
 *
 * 这里用 Playwright 拦截 WebSocket,模拟后端发出"拒答"风格的 final 帧,
 * 验证前端 UI 渲染行为(气泡文本可读、不是空白、不是 thinking)。
 *
 * 覆盖拒答信号词: 后端 REJECT fallback("抱歉...") + 多种 LLM 自拒答表达,
 * 只要任一出现即视为正确渲染。
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

async function installMockWs(page: Page, frames: MockFrame[]): Promise<void> {
  await page.addInitScript((initialFrames: MockFrame[]) => {
    class MockWS extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      readyState = 0;
      url: string;
      // 关键:frames 在 connect 时**不**派发,而是 client 第一次 send 时才派发,
      // 模拟"client 发请求 → server 处理 → server 回复"的真实节奏。否则
      // connect 时同步派发会在 user click send 之前就发完所有帧(包括 done),
      // 导致 setIsLoading(false) 在 user send 之前跑了一次(对 isLoading=false noop),
      // 之后 user send 触发 setIsLoading(true),前端永远卡住,等不到终止帧。
      private sent: number = 0;
      private queue: MockFrame[];
      private onmessageFn: ((ev: MessageEvent) => void) | null = null;
      constructor(url: string) {
        super();
        this.url = url;
        this.readyState = 1;
        this.queue = initialFrames;
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
            this.onmessageFn = fn;
          },
          configurable: true,
        });
      }
      private replay(): void {
        if (!this.onmessageFn || this.sent === 0) return;
        const fn = this.onmessageFn;
        for (const frame of this.queue) {
          try {
            fn(new MessageEvent('message', { data: JSON.stringify(frame) }));
          } catch {
            /* ignore */
          }
        }
        // 末尾发 done(除非队列中已有 done)
        const hasDone = this.queue.some((f) => f.type === 'done');
        if (!hasDone) {
          try {
            fn(new MessageEvent('message', { data: JSON.stringify({ type: 'done', event_id: 999 }) }));
          } catch {
            /* ignore */
          }
        }
      }
      send(_data: string | ArrayBuffer | Blob | ArrayBufferView): void {
        const w = window as unknown as { __nexusWsSent?: unknown[] };
        w.__nexusWsSent = w.__nexusWsSent ?? [];
        w.__nexusWsSent.push(_data);
        this.sent += 1;
        // 第一次 send 才派发所有帧,模拟"client 发 → server 回"
        if (this.sent === 1) {
          // 用 setTimeout 0 让 send() 同步返回后再派发,避免影响测试时间线
          window.setTimeout(() => this.replay(), 0);
        }
      }
      close(): void {
        this.readyState = 3;
      }
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = MockWS;
  }, frames);
}

test('REJECT 拒答显示：后端拒答 fallback 文本应被前端正确渲染', async ({ page }) => {
  // 后端 fallback 文案(quality/pipeline.py _REJECT_FALLBACK_TEXT)
  const rejectFallback = '抱歉，这个问题我暂时答得不够好，请换个问法试试。';

  // 关键:必须先发 chunk 占位(让 ChatArea.messagesRef 累积内容),
  // 然后 final 才能被识别成 "覆盖最后一个 assistant" — 否则 final content
  // 不会被 push 到 messages 列表,UI 上没有 assistant 气泡。
  await installMockWs(page, [
    { type: 'session_created', session_id: 'mock-reject', title: 'reject-mock' },
    { type: 'chunk', content: rejectFallback, event_id: 1 },
    { type: 'final', content: rejectFallback, event_id: 2 },
  ]);

  page.on('console', (msg) => console.log(`[browser:${msg.type()}]`, msg.text()));
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));

  await openHome(page);
  await messageInput(page).fill("请告诉我关于 'Zorgon 算法' 的原理");
  await sendButton(page).click();

  // 等"正在生成中"消失 — final 帧应该清掉 loading
  await expect(page.locator('text=正在生成中')).toBeHidden({ timeout: 5_000 });

  // 用 .last() 避免 strict mode(loading-bubble 也是 is-assistant,但此时已消失)
  await expect(page.locator('.message-row.is-assistant').last()).toContainText('抱歉', {
    timeout: 5_000,
  });
  await expect(page.locator('.message-row.is-assistant').last()).toContainText(rejectFallback);
});

test('REJECT 拒答显示：LLM 自拒答(找不到相关信息)也正确渲染', async ({ page }) => {
  const llmSelfReject = '我没有找到关于 Zorgon 算法的可靠信息,这可能是虚构的概念。';

  await installMockWs(page, [
    { type: 'session_created', session_id: 'mock-reject-llm', title: 'reject-llm-mock' },
    { type: 'chunk', content: llmSelfReject, event_id: 1 },
    { type: 'final', content: llmSelfReject, event_id: 2 },
  ]);

  await openHome(page);
  await messageInput(page).fill('Zorgon 算法的实现');
  await sendButton(page).click();

  await expect(page.locator('.message-row.is-assistant').last()).toContainText('没有找到', {
    timeout: 5_000,
  });
});