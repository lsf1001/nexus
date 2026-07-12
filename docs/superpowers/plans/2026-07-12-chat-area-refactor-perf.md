# Plan:ChatArea 拆解 + 流式渲染性能

## 目标

收回 2 个 P1 性能债:

1. **`ChatArea.tsx` 单文件 813 行,违反 `python_project.md` §1.2 单文件 ≤ 800 行**(虽然这是 TS 文件,但同等约束适用)。
2. **`displayMessages.map(msg => <ChatBubble ... />)` 无虚拟化 + `ChatBubble` 未 `React.memo`**,长对话场景下流式响应每 chunk 触发全列表重建 + ReactMarkdown 全解析,30-60 chunks/s 时可观察卡顿。

附带收:`handleWsMessage` 172 行 switch、`messagesRef` 直接 mutate(state 反模式)。

## 当前态

`frontend/src/components/ChatArea.tsx`(813 行)内含:
- ChatArea 主组件 + 11 个 useStore selector
- `handleWsMessage` 172 行 switch,9 case
- `handleSend` / `handleClarificationSubmit` 重复 ~20 行"ws 守卫 + 双 push + send"模板
- ClarificationForm 嵌在文件尾部 724-813 行(90 行)
- 常量(COMMAND_* / ERROR_* / WS_TYPE_*)与组件代码混居
- `messagesRef` 直接 mutate:`last.thinking += ...; last.content += ...`(反模式)
- `scrollIntoView({behavior:'smooth'})` 每个 chunk 都触发

## 拆解方案

### Phase 1:组件拆分(独立单元,无副作用)

| 新文件 | 来源 | 职责 |
| --- | --- | --- |
| `frontend/src/components/ChatArea/index.tsx` | ChatArea 主体 | 编排:订阅 store / 派发事件 / 转发给子组件 |
| `frontend/src/components/ChatArea/ClarificationForm.tsx` | 724-813 | 澄清提问表单,React.memo |
| `frontend/src/components/ChatArea/CommandBubble.tsx` | 拆分 | 错误码 / 命令式系统消息气泡 |
| `frontend/src/components/ChatArea/ChatBubble.tsx` | 已有但加 memo | React.memo + props 自定义比较,只重渲染当前 chunk |
| `frontend/src/components/ChatArea/MessageList.tsx` | 拆分 displayMessages 部分 | 虚拟列表 + 滚动锚定 |
| `frontend/src/components/ChatArea/constants.ts` | 提走 | COMMAND_* / ERROR_* / WS_TYPE_* / 超时阈值 |
| `frontend/src/components/ChatArea/types.ts` | 拆分 | WsFrame / MessageView / PendingConfirmation |
| `frontend/src/components/ChatArea/hooks/useWsMessageRouter.ts` | handleWsMessage 拆走 | 9 case 分发器,每个 case 一个 handler 函数 |
| `frontend/src/components/ChatArea/hooks/useChatSend.ts` | handleSend | "双 push + send + watchdog" |
| `frontend/src/components/ChatArea/hooks/useWatchdog.ts` | 复用 useLoadingWatchdog | 流式超时/重试 |
| `frontend/src/components/ChatArea/hooks/useAutoScroll.ts` | scrollIntoView 拆走 | RAF 节流 + 用户主动滚动检测 |

**为什么按"职责"拆而不是按"代码量"拆**:每个新文件单元都可独立测试,改一处不影响其它;后续 PR review diff 也更聚焦。

### Phase 2:`ChatBubble` memo + chunk-rate 重渲染隔离

1. **React.memo + 自定义比较器**:
   ```ts
   export const ChatBubble = React.memo(ChatBubbleInner, (prev, next) => {
     // 只在 message 内容变化时重渲染:content / thinking / status
     return prev.message.id === next.message.id
       && prev.message.content === next.message.content
       && prev.message.thinking === next.message.thinking
       && prev.message.status === next.message.status
   })
   ```

2. **chunk-rate 隔离**:
   - 流式响应过程中,**仅**当前活跃消息(thinking + content 还在变)的 ChatBubble 接受新 chunk
   - 已完成的 ChatBubble `props` 不变 → memo 直接跳过
   - ReactMarkdown 解析对每条 message **缓存**(key=`id + version` 的 useMemo),仅当前 chunk 重 parse

3. **`MessageList` 虚拟化**:
   - 引入 `react-window` 或 `react-virtuoso`(后者对流式追加更友好:支持 anchor 滚动)
   - `itemSize`:每条 bubble 估高 80-200px(流式时 `thinking + content + actions`)
   - `overscan: 5`(避免快速滚动白屏)
   - **不要**直接对整 `<MessageList>` 虚拟化;**保留**外层 wrapper 处理 ErrorBoundary/LoadingState

### Phase 3:消除 `messagesRef` mutate 反模式

**现状**:`messagesRef.current.push(userMsg)` + `last.thinking += ...; last.content += ...`。

**问题**:React 18+ Concurrent 模式下,mutate ref 不会触发 commit,但**会**与 useEffect / useMemo 依赖 race,产生 stale state。

**方案**:把"流式累积"状态从 store 拆到 `useChatStream` hook 内部(组件私有 state),只在最终落库时 push 进 store。

```ts
function useChatStream() {
  const [streaming, setStreaming] = useState<MessageView | null>(null)
  const appendChunk = useCallback((chunk: ChunkPayload) => {
    setStreaming(prev => prev ? { ...prev, content: prev.content + chunk.content, thinking: (prev.thinking ?? '') + (chunk.thinking ?? '') } : buildMessageFromChunk(chunk))
  }, [])
  const finalize = useCallback(() => {
    // 落 store,清 streaming
  }, [])
  return { streaming, appendChunk, finalize }
}
```

- `streaming` 是组件私有 React state(用 `useState` 而非 mutate ref)
- `appendChunk` 在流式期间反复 setState,但只有当前 `<ChatBubble key={streaming.id}>` 接收新 props,其它 bubble 通过 memo 跳过
- 流式结束 → `finalize()` 推 store + 清空 streaming

### Phase 4:`handleWsMessage` switch 拆分发器

```ts
// useWsMessageRouter.ts
type Handler = (frame: WsFrame, ctx: RouterCtx) => void
const HANDLERS: Record<WsFrame['type'], Handler> = {
  thinking: handleThinking,
  chunk: handleChunk,
  final: handleFinal,
  done: handleDone,
  error: handleError,
  confirmation_request: handleConfirmationRequest,
  confirmation_response: handleConfirmationResponse,
  resume_ack: handleResumeAck,
  system: handleSystem,
}
export function useWsMessageRouter() {
  const ctx = useRouterCtx()  // dispatch / store / sendWs 等
  return useCallback((frame: WsFrame) => {
    HANDLERS[frame.type]?.(frame, ctx) ?? console.error('unknown frame', frame)
  }, [ctx])
}
```

每个 handler 独立可测;新增 frame type 只在 HANDLERS 加一行。

### Phase 5:scrollIntoView 节流

`useAutoScroll(anchorRef)` hook:
- 用 `IntersectionObserver` 监听底部 sentinel
- 仅当 sentinel in-viewport + 流式活跃 → smooth scroll
- 用户主动上滚(检测 wheel 事件)→ **暂停**自动滚动,直到用户回到底部
- RAF 节流:同一帧多次 chunk 合并为一次 scroll

## 测试

### 单元测试(vitest)

- `useChatStream.test.ts`:`appendChunk` 状态累积 / `finalize` 落 store
- `useWsMessageRouter.test.ts`:9 个 handler 各自状态正确
- `useAutoScroll.test.ts`:节流 + 用户上滚暂停

### E2E(Playwright)

- `chat-long-session.spec.ts`:模拟 100+ 消息对话,验证:
  - 流式响应时,前 50 条已完成的 ChatBubble 不触发 React.memo 重渲染(fixture inject 一计数 mock)
  - 滚动锚定不丢位置
  - 中断 / 续传不破坏消息列表
- `chat-bubble-memo.spec.ts`:手动构造"每 chunk 触发 100+ setState"场景,断言 React Profiler commit 数 < N

### 性能基准

- 跑 `frontend/src/bench/chat-render.bench.ts`(新):长对话(200 消息)+ 流式(模拟 60 chunks/s)
  - 目标:每 chunk 平均 < 16ms(60fps),最坏 < 32ms
  - 当前:流式 60 chunks/s 时,长对话下肉眼可见 200ms+ 卡顿

## 验收

- `frontend/src/components/ChatArea.tsx` 文件**不存在**(全部迁出)
- `ls -la frontend/src/components/ChatArea/` 有 8-10 个新文件,每个 ≤ 200 行
- `npm run lint` 0 error
- `npm run test:e2e` 全过
- 性能基准达标(60fps,长对话不卡)

## 风险

- **虚拟列表对代码高亮 / markdown 嵌套高的消息不友好**:预估每条 bubble 最大高度 500px,overscan 5 通常够用;对超长代码块(bubble > 1000px),允许 ChatBubble 自渲染但不虚拟化(白名单)。
- **`messagesRef` 移除需要全链路重测**:HITL 弹窗 → continuation → 续传路径上,所有"in-flight 消息"的中间态都依赖 ref;新 `useChatStream` 必须保持等价时序。
- **react-virtuoso 引入增加 bundle 50kb**:可接受(产物 ~700kb → 750kb)。
- **`handleWsMessage` 拆分发器期间,某些 frame type 上下文依赖可能漏**:用 typecheck + e2e 全覆盖。

## 实施顺序(commit 拆分)

1. `refactor(chat-area): extract ChatBubble + CommandBubble + ClarificationForm`
2. `refactor(chat-area): extract useWsMessageRouter + useChatSend + useAutoScroll hooks`
3. `perf(chat-bubble): React.memo + content hash cache`
4. `feat(message-list): react-virtuoso virtualized list`
5. `refactor(chat-area): replace messagesRef mutate with useChatStream state`
6. `perf(chat-scroll): RAF-throttled auto-scroll with user-override`
7. `test(chat-area): unit + e2e + render benchmark`
8. `docs(chat-architecture): ChatArea module map + state lifecycle`