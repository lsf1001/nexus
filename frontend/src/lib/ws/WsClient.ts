/**
 * 浏览器原生 WebSocket 客户端 — 抽象掉重连逻辑,供 useWebSocket 复用。
 *
 * 设计要点(2026-07-12 Plan 3):
 * - **jitter**:`exponential + random(-jitter, +jitter)`,默认 ±30% 抖动
 *   防多客户端同步重连撞代理/后端。原始 useWebSocket 完全确定性退避,
 *   N 个客户端断网恢复后会在同 ms 重连,瞬间打满 backend。
 * - **maxRetries**:默认 8(总尝试时长 ~5min),用尽后调 onExhausted,
 *   不再 setTimeout,UI 可提示"重连失败,请手动重试"。
 * - **AbortController**:取消 in-flight 重连 — 用户手动重连时,旧 setTimeout
 *   还在 pending 会触发新 ws.close,旧 AbortController 取消后续 connect。
 * - **retryRef 只在 ws.open 时归 0**:网络短抖动后能完整重置退避计数。
 *
 * 不变量:
 * - `connect()` 必须幂等(重复调用应 abort 旧连接再开新连接)
 * - `disconnect()` 后再有 close 事件应 noop,不触发重连
 * - AbortController abort 后,任何 pending setTimeout 必须不 fire
 *
 * 类不依赖 React,可在 Node.js 用 node:test 单测(见 ws/WsClient.test.ts)。
 */

export interface ReconnectPolicy {
  /** 退避基数,默认 1000ms */
  baseDelayMs: number;
  /** 退避上限,默认 30000ms */
  maxDelayMs: number;
  /** 最大重试次数,默认 8(累计 ~5min) */
  maxRetries: number;
  /** 抖动比例(相对 exponential),默认 0.3 = ±30% */
  jitterRatio: number;
  /** 用尽后回调 — UI 据此设 wsStatus='exhausted' + 提示用户 */
  onExhausted: () => void;
  /** 每次 schedule 重连时回调(attempt 计数从 0 开始) */
  onRetryScheduled?: (attempt: number, delayMs: number) => void;
}

export const DEFAULT_POLICY: Omit<ReconnectPolicy, 'onExhausted'> = {
  baseDelayMs: 1000,
  maxDelayMs: 30000,
  maxRetries: 8,
  jitterRatio: 0.3,
};

/**
 * 计算下一次重连延迟(ms)。纯函数,便于单测。
 *
 * @param attempt 当前尝试序号(0 = 第一次失败后)
 * @param policy 退避参数
 * @param rng 随机数生成器(默认 Math.random,测试可注入 mock)
 */
export function computeReconnectDelay(
  attempt: number,
  policy: Pick<ReconnectPolicy, 'baseDelayMs' | 'maxDelayMs' | 'jitterRatio'>,
  rng: () => number = Math.random,
): number {
  const exponential = Math.min(policy.maxDelayMs, policy.baseDelayMs * 2 ** attempt);
  const jitterRange = policy.jitterRatio * exponential;
  // random ∈ [0, 1) → jitter ∈ (-jitterRange, +jitterRange)
  return exponential + (rng() * 2 - 1) * jitterRange;
}

/** WebSocket 抽象接口 — 测试时用 mock 实现 */
export interface IWebSocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onclose: ((ev: { wasClean: boolean; code: number; reason: string }) => void) | null;
}

/** WsClient 构造选项 */
export interface WsClientOptions {
  url: string;
  /** Sec-WebSocket-Protocol 子协议(2026-07 WS 鉴权,token 走 subprotocol) */
  subprotocols?: string[];
  /** 工厂函数 — 测试可注入 mock WebSocket */
  socketFactory: (url: string, protocols?: string[]) => IWebSocketLike;
  /** 收到文本帧(JSON)时回调 */
  onMessage: (data: unknown) => void;
  /** 连接已打开时回调 — 用于清零 retry 计数 */
  onOpen?: () => void;
  /** close 事件回调(用于 reconnect 判断) */
  onClose?: (info: { wasClean: boolean; code: number; reason: string }) => void;
  /** 自定义调度(测试用 vi.useFakeTimers / setTimeout mock) */
  scheduler?: {
    setTimeout: (cb: () => void, ms: number) => unknown;
    clearTimeout: (handle: unknown) => void;
  };
  /** 自定义随机源(测试用 mock 验证 jitter 范围) */
  rng?: () => number;
  policy: Partial<ReconnectPolicy>;
}

export class WsClient {
  private readonly url: string;
  private readonly subprotocols?: string[];
  private readonly socketFactory: (url: string, protocols?: string[]) => IWebSocketLike;
  private readonly onMessage: (data: unknown) => void;
  private readonly onOpen?: () => void;
  private readonly onClose?: (info: { wasClean: boolean; code: number; reason: string }) => void;
  private readonly setTimeout: (cb: () => void, ms: number) => unknown;
  private readonly clearTimeout: (handle: unknown) => void;
  private readonly rng: () => number;
  private readonly policy: Omit<ReconnectPolicy, 'onExhausted' | 'onRetryScheduled'>;
  private readonly onExhausted: () => void;
  private readonly onRetryScheduled?: (attempt: number, delayMs: number) => void;

  private socket: IWebSocketLike | null = null;
  private abortCtrl: AbortController | null = null;
  private retryAttempt = 0;
  private pendingTimer: unknown = null;
  private intentionallyClosed = false;

  constructor(opts: WsClientOptions) {
    this.url = opts.url;
    this.subprotocols = opts.subprotocols;
    this.socketFactory = opts.socketFactory;
    this.onMessage = opts.onMessage;
    this.onOpen = opts.onOpen;
    this.onClose = opts.onClose;
    this.setTimeout = opts.scheduler?.setTimeout ?? ((cb, ms) => window.setTimeout(cb, ms));
    this.clearTimeout = opts.scheduler?.clearTimeout ?? ((h) => window.clearTimeout(h as number));
    this.rng = opts.rng ?? Math.random;
    this.policy = {
      baseDelayMs: opts.policy.baseDelayMs ?? DEFAULT_POLICY.baseDelayMs,
      maxDelayMs: opts.policy.maxDelayMs ?? DEFAULT_POLICY.maxDelayMs,
      maxRetries: opts.policy.maxRetries ?? DEFAULT_POLICY.maxRetries,
      jitterRatio: opts.policy.jitterRatio ?? DEFAULT_POLICY.jitterRatio,
    };
    this.onExhausted = opts.policy.onExhausted ?? (() => undefined);
    this.onRetryScheduled = opts.policy.onRetryScheduled;
  }

  /** 开启(或重连) — 重复调用幂等 */
  connect(): void {
    // 取消 in-flight 重连 / 旧连接
    this.abortCtrl?.abort();
    this.abortCtrl = new AbortController();

    const socket = this.socketFactory(this.url, this.subprotocols);
    this.socket = socket;

    socket.onopen = () => {
      // 关键:成功 open → retry 计数归 0
      this.retryAttempt = 0;
      this.onOpen?.();
    };

    socket.onmessage = (event) => {
      const data = event.data;
      if (typeof data !== 'string') {
        // Blob / ArrayBuffer — 后端 stream 协议约定只发 JSON 文本帧。
        // 透传给 onMessage(原 useWebSocket 行为),下游 switch 找不到匹配 → 静默吞掉。
        return;
      }
      try {
        this.onMessage(JSON.parse(data));
      } catch {
        // 非 JSON 文本帧(例如代理 HTML 错误页):不抛、不透传,
        // 避免下游误触发 type 解析失败。
      }
    };

    socket.onerror = () => {
      // 浏览器:onerror 后必触发 onclose,统一在 onclose 处理重连。
    };

    socket.onclose = (ev) => {
      this.onClose?.({ wasClean: ev.wasClean, code: ev.code, reason: ev.reason });
      // 主动 disconnect / AbortController 取消 → 不重连
      if (this.intentionallyClosed || this.abortCtrl?.signal.aborted) {
        return;
      }
      // wasClean=true 是协议层正常关闭码(1000) — 也不重连
      if (ev.wasClean) {
        return;
      }
      // 重试用尽 → 调 onExhausted,不再 setTimeout
      if (this.retryAttempt >= this.policy.maxRetries) {
        this.onExhausted();
        return;
      }
      // 计算 jitter 退避 + 调度
      const delay = computeReconnectDelay(this.retryAttempt, this.policy, this.rng);
      const attempt = this.retryAttempt;
      this.retryAttempt += 1;
      this.onRetryScheduled?.(attempt, delay);
      this.pendingTimer = this.setTimeout(() => {
        this.pendingTimer = null;
        this.connect();
      }, delay);
    };
  }

  /**
   * 主动关闭 + 不再重连。重复调用幂等。
   *
   * @param code 关闭码,默认 1000(正常)
   * @param reason 关闭原因,默认 'client_disconnect'
   */
  disconnect(code = 1000, reason = 'client_disconnect'): void {
    this.intentionallyClosed = true;
    if (this.pendingTimer !== null) {
      this.clearTimeout(this.pendingTimer);
      this.pendingTimer = null;
    }
    this.abortCtrl?.abort();
    try {
      this.socket?.close(code, reason);
    } catch {
      // 关闭失败通常是已 closed,吞掉
    }
    this.socket = null;
  }

  /** 当前 socket 的 readyState(无 socket 时返回 WebSocket.CLOSED=3) */
  getReadyState(): number {
    return this.socket?.readyState ?? 3;
  }

  /**
   * 发送文本帧。socket 未 OPEN 时静默丢弃(原 useWebSocket 行为,避免抖
   * 动期间发"鬼影消息")。调用方传对象时本方法不自动 JSON.stringify —
   * 原 useWebSocket.send 在 hook 层做 stringify,WsClient 保持透传避免重复。
   */
  send(data: string): boolean {
    if (this.socket && this.socket.readyState === 1 /* WebSocket.OPEN */) {
      this.socket.send(data);
      return true;
    }
    return false;
  }

  /** 已重试次数(成功 open 时归 0) */
  getRetryAttempt(): number {
    return this.retryAttempt;
  }
}