# Plan:WS 重连稳态加固 + useWebSocket 改造

## 目标

收回 1 个 P1 可靠债:

- `frontend/src/hooks/useWebSocket.ts:95` 重连退避 **无 jitter**,易多端同步重连撞代理/服务端;**无 maxRetries**,失败后无限循环 → 后端 60s `wait_for(_agent_ready_event.wait())` 还没就绪时,**所有 WS 客户端同步发起第 N 次重连**,瞬间打满后端 / 代理。

## 当前态

`frontend/src/hooks/useWebSocket.ts`(约 130 行):
- 重连退避:`Math.min(maxDelay, baseDelay * 2 ** retryRef.current)`,`baseDelay=1000`,`maxDelay=30000`
- 没有 jitter(完全确定性退避)
- `retryRef.current++` 永不重置,**或**只在连接成功后重置(要确认代码)
- 没 `AbortController`,没法 cancel 旧连接

`frontend/src/hooks/useTauriWs.ts`(类似实现):
- 失败时注入 `error_code: ws_open_failed` 的伪 frame

`nexus/backend/main.py:415-420`:
- 首条 WS 消息 await 60s,等 `_agent_ready_event.wait()`(Agent + MCP 构造期)
- 若 60s 内 Agent 未就绪,WS 客户端断连,触发重连

## 实施步骤

### Phase 1:`useWebSocket` 全面重写

```ts
interface ReconnectPolicy {
  baseDelayMs: number        // 默认 1000
  maxDelayMs: number         // 默认 30000
  maxRetries: number         // 默认 8(累计 ~ 5min 总尝试时间)
  jitterMs: number           // 默认 0.3(相对 baseDelay 的 ±30% 抖动)
  onExhausted: () => void    // 用尽后回调(走 useStore.setWsStatus='exhausted')
}

export function useWebSocket(url: string, token: string, policy: Partial<ReconnectPolicy> = {}) {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const timeoutRef = useRef<number | null>(null)

  const computeDelay = useCallback((attempt: number) => {
    const exponential = Math.min(policy.maxDelayMs ?? 30000, (policy.baseDelayMs ?? 1000) * 2 ** attempt)
    const jitterRange = (policy.jitterMs ?? 0.3) * exponential
    return exponential + (Math.random() * 2 - 1) * jitterRange
  }, [policy])

  const connect = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    const ws = new WebSocket(url, [`nexus-v1.token=${token}`])
    wsRef.current = ws
    const onOpen = () => { retryRef.current = 0; /* 帧协议 subprotocol 同步 */ }
    const onClose = (ev: CloseEvent) => {
      if (ev.wasClean) return
      if (retryRef.current >= (policy.maxRetries ?? 8)) {
        onExhausted()
        return
      }
      const delay = computeDelay(retryRef.current)
      retryRef.current++
      timeoutRef.current = window.setTimeout(connect, delay)
    }
    ws.addEventListener('open', onOpen)
    ws.addEventListener('close', onClose)
    ws.addEventListener('message', ...)
    ws.addEventListener('error', ...)
  }, [url, token, policy, computeDelay])

  useEffect(() => {
    connect()
    return () => {
      abortRef.current?.abort()
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current)
      wsRef.current?.close(1000, 'unmount')
    }
  }, [connect])
  ...
}
```

要点:
- **jitter**:`exponential + random(-jitter, +jitter)`,默认 ±30% 抖动
- **maxRetries**:默认 8(总尝试时长 ~ 5min),用尽后回调 `onExhausted` → store 设 `wsStatus: 'exhausted'` → UI 提示用户"重连失败,请手动重试"
- **AbortController**:cancel in-flight 重连,避免 race(典型 bug:用户手动点击 reconnect,旧的 setTimeout 还在 pending)
- **close reason**:`unmount` 走 1000 正常关闭码;网络断开走 1006
- **`retryRef.current` 只在 ws open 时重置 0**(现在就要确认 — 若只在 close-重连-递增的循环里递增,never resets)

### Phase 2:与 useTauriWs 抽象统一

`useTauriWs.ts` 复刻同样的 ReconnectPolicy;或更彻底,**抽出 `WsClient` 类**:

```ts
// frontend/src/lib/ws/WsClient.ts
export class WsClient {
  constructor(private opts: { url: string; token: string; policy: ReconnectPolicy; onFrame: (f: WsFrame) => void }) {}
  connect(): void
  disconnect(reason?: string): void
  send(payload: object): void
  private scheduleReconnect(): void
}
```

- `useWebSocket` / `useTauriWs` 都是 thin wrapper,只是 `new WebSocket` vs `invoke('ws_connect', ...)`
- ReconnectPolicy 单点定义,3 个 e2e 都覆盖

### Phase 3:`wsStatus` 进 useStore slice

新 slice:
```ts
type WsStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'exhausted' | 'closed'
interface WsSlice {
  wsStatus: WsStatus
  setWsStatus: (s: WsStatus) => void
  reconnectAttempts: number
  setReconnectAttempts: (n: number) => void
}
```

UI:`<ConnectionIndicator />`(工具栏右侧)
- `reconnecting` → 显示"S${retry}/8"小字 + 旋转图标
- `exhausted` → 红色叹号 + 提示"重连失败,请检查后端"

### Phase 4:后端配合

1. `nexus/backend/main.py`:
   - `_agent_ready_event.wait()` 60s 超时 → 改 90s(给 MCP 构造更多余量)
   - 超时后**不要**断 WS 客户端,而是发 `system` frame `{type:'system', payload:{event:'agent_init_timeout', retry_in:5}}`,客户端用此作为 retry hint(增加 baseDelay)
2. 新增 WS error code:`service_restarting`(503 service unavailable),客户端按 Retry-After header 决定 backoff

### Phase 5:测试

#### 单元测试

- `WsClient.test.ts`:
  - 第 N 次重连 jitter 范围 [base * 0.7, base * 1.3]
  - 第 9 次重连(超过 maxRetries)→ 触发 `onExhausted`,**不再** setTimeout
  - `disconnect()` 后再有 close 事件 → **不**触发重连
  - AbortController 取消后 setTimeout 不再 fire
  - `retryRef` 在 ws.open 时归 0

#### E2E

- `ws-reconnect-jitter.spec.ts`:
  - 后端启动 100 个客户端同时断连,统计重连时间分布,验证 jitter 真实生效(否则会同步)
- `ws-reconnect-exhausted.spec.ts`:
  - 后端拒连(关掉 mock),客户端走完 8 次重连,验证最终 `wsStatus: 'exhausted'`,UI 显示提示

## 验收

- `frontend/src/lib/ws/WsClient.ts` 存在,`useWebSocket` / `useTauriWs` 都是 thin wrapper
- `useWebSocket.ts` 行数 ≤ 80 行(原 ~130 行,实际可瘦身)
- `useStore.ts` 增加 `wsStatus` slice
- `<ConnectionIndicator />` 渲染正确
- 单元 + e2e 测试覆盖 jitter / maxRetries / AbortController

## 风险

- **jitter 在测试环境需要 mock**:vi.useFakeTimers / `Math.random` mock,否则断言不稳
- **`AbortController` 与 `WebSocket.close` 行为**:浏览器自动清理,但 polyfill 不保证(我们走 Tauri 2 + 现代 Chromium,应该 ok)
- **`WsClient` 抽离后旧 `useWebSocket` API 兼容性**:可以保留 facade 1 个版本

## 实施顺序(commit 拆分)

1. `feat(ws-client): extract WsClient class with jitter + maxRetries`
2. `refactor(ws): useWebSocket becomes thin wrapper over WsClient`
3. `refactor(ws): useTauriWs becomes thin wrapper over WsClient`
4. `feat(store): wsStatus slice + ConnectionIndicator UI`
5. `feat(ws): server-side agent_init_timeout frame with retry hint`
6. `test(ws-client): jitter/maxRetries/AbortController coverage + e2e`