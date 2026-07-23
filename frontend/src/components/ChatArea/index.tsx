/**
 * ChatArea 顶层编排:协调 hooks + 调用子组件,业务实现全部委托给 ./*.tsx
 * 与 ./hooks/*.ts;只承载 wiring 与 React DOM 顶层布局。
 *
 * 不变行为与原 818 行单文件等价(resetTrigger / WS 鉴权 / watchdog / 滚动对齐
 * 都保留)。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useWsConnection } from '../../hooks/useWsConnection';
import { useLoadingWatchdog } from '../../hooks/useLoadingWatchdog';
import { getApiBase, getWsToken } from '../../lib/api';

import { ClarificationForm } from './ClarificationForm';
import { ConfirmationCard } from './ConfirmationCard';
import { Composer } from './Composer';
import { EmptyState } from './EmptyState';
import { ErrorBanner } from './ErrorBanner';
import { MessageList } from './MessageList';
import { ModelSelector } from './ModelSelector';
import { useAutoScroll } from './hooks/useAutoScroll';
import { useChatAreaActions } from './hooks/useChatAreaActions';
import { useChatSend } from './hooks/useChatSend';
import { type ChatStreamActions, useChatStream } from './hooks/useChatStream';
import { useDraft } from './hooks/useDraft';
import { useWsMessageRouter, type WsRouterCtx } from './hooks/useWsMessageRouter';
import type { LastError, PendingClarification } from './types';

export interface ChatAreaProps {
  resetTrigger?: number;
  onConnectedChange?: (connected: boolean) => void;
  onSessionCreated?: (sessionId: string, title: string) => void;
  conversationId?: string | null;
  connectionState?: 'connecting' | 'online' | 'offline';
  activeConversationTitle?: string | null;
  conversationCount?: number;
}

export function ChatArea({
  resetTrigger,
  onConnectedChange,
  onSessionCreated,
  conversationId: conversationIdProp,
  connectionState = 'connecting',
}: ChatAreaProps) {
  const [input, setInput] = useState('');
  const [lastError, setLastError] = useState<LastError | null>(null);
  const [pendingClarification, setPendingClarification] =
    useState<PendingClarification | null>(null);
  // 滚动容器 — 用作 useAutoScroll 的滚动目标(必须指向 .chat-scroll 自己,
  // 不能用末尾的空 div messagesEndRef — 那个 div 没有 overflow,smooth scrollTo
  // 不会带动父容器,2026-07-13 真 LLM multi-turn 暴露 viewport ratio 0)。
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const resetTriggerRef = useRef(resetTrigger ?? 0);
  const sessionIdRef = useRef<string | null>(conversationIdProp);

  // store 选择器 — useWsMessageRouter 的 ctx 不能拿这些 selector(其引用每次
  // render 都会变),所以 router 内部读 useStore.getState()。
  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const showThinking = useStore((s) => s.showThinking);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const displayMessages = useStore((s) => s.conversationMessages);
  const clearConversationMessages = useStore((s) => s.clearConversationMessages);
  const pendingConfirmation = useStore((s) => s.pendingConfirmation);
  const setPendingConfirmation = useStore((s) => s.setPendingConfirmation);

  useEffect(() => {
    sessionIdRef.current = conversationIdProp;
  }, [conversationIdProp]);

  // === 消息流操作(替代原 messagesRef mutate) ===
  const stream: ChatStreamActions = useChatStream();

  // === watchdog:30s 无终止帧强制清 loading ===
  const { arm: armWatchdog, disarm: disarmWatchdog } = useLoadingWatchdog({
    setIsLoading,
    setLastError,
  });

  // === resetTrigger 同步状态 ===
  // 2026-07-22 修复:必须重置 isLoading + disarm watchdog。否则上一轮流如果
  // 是经 mock reflection / 已停止 路径提前结束(stoppedRef 门控掉后续 chunk,
  // 或 mock LLM 走反思 done 帧的时序刚好让 last content 不写 store),handleDone
  // 帧可能不会被 wsHandlers 收到 → store.isLoading 残留 true → Composer 渲染
  // stop-button(send-button stop-button) → 用户切到新会话后 sendButton selector
  // 命中 stop-button 而不是 send → click 不发消息(quick-prompts-and-history
  // spec 暴露的就是这条链路)。
  // 必须放在 useLoadingWatchdog 之后 — disarmWatchdog 是它的返回值,在
  // 调用前 closure 引用会撞 TDZ(React 19 + Vite + ReferenceError)。
  useEffect(() => {
    if (resetTrigger && resetTrigger > resetTriggerRef.current) {
      clearConversationMessages();
      setInput('');
      setIsLoading(false);
      disarmWatchdog();
      setPendingClarification(null);
      setPendingConfirmation(null);
      setLastError(null);
    }
    resetTriggerRef.current = resetTrigger ?? 0;
  }, [resetTrigger, clearConversationMessages, setIsLoading, disarmWatchdog, setPendingConfirmation]);

  // === WS 连接 — 鉴权走 subprotocol ===
  // 2026-07-20:WsRouterCtx 不再含 stream — wsHandlers.handleChunk / handleThinking
  // / handleFinal 都改用 useStore.getState().appendAssistantPatch,直接读 store,
  // 完全不依赖 ctx.stream。WsRouterCtx 现在只剩 React setter + watchdog,引用
  // 全是 useState setter(本就稳定)+ useCallback(依赖稳定),useMemo 几乎可以
  // 移除 — 这里保留 useMemo 是为了未来扩展 setLastError 等可能在 ChatArea 内
  // 重建的 setter 仍走稳定路径。
  const wsCtx = useMemo<WsRouterCtx>(
    () => ({
      setLastError,
      setIsLoading,
      setPendingClarification,
      setPendingConfirmation,
      disarmWatchdog,
      onSessionCreated,
    }),
    [setLastError, setIsLoading, setPendingClarification, setPendingConfirmation, disarmWatchdog, onSessionCreated],
  );
  const handleWsMessage = useWsMessageRouter(wsCtx);

  const wsUrl = useMemo(() => {
    const wsBase = getApiBase().replace(/^http/, 'ws');
    return `${wsBase}/api/ws`;
  }, []);
  const wsToken = useMemo(() => getWsToken(), []);
  const {
    connected: wsHookConnected,
    send: wsSend,
    getReadyState,
  } = useWsConnection({
    url: wsUrl,
    token: wsToken,
    onMessage: handleWsMessage,
  });

  useEffect(() => {
    setWsConnected(wsHookConnected);
    onConnectedChange?.(wsHookConnected);
  }, [wsHookConnected, setWsConnected, onConnectedChange]);
  // 把下游 send 暴露给上游 input/textarea — 用 ref 桥避免每次 render 重建 sendRef
  const sendFn = useCallback(
    (msg: Parameters<typeof wsSend>[0]) => wsSend(msg),
    [wsSend],
  );

  // === 自动滚动(rAF) — 滚动容器是 .chat-scroll(必须 overflow:auto),
  // 不能是末尾空 div messagesEndRef — 那个 div 没有 overflow,smooth
  // scrollTo 不会带动父容器。2026-07-13 真 LLM multi-turn 暴露 viewport
  // ratio 0,根因就在这里。===
  // 第十一轮:返回 userScrolledUp + scrollToBottom,ChatArea 条件渲染浮动按钮。
  const { userScrolledUp, scrollToBottom } = useAutoScroll({
    trigger: [displayMessages.length, isLoading],
    containerRef: chatScrollRef,
  });

  // === 草稿持久化(第十一轮,2026-07-23) ===
  // 见 ./hooks/useDraft.ts 实现注释。Level 1 行为:
  //   - 读:挂载 + conversationId 为空 → 读 localStorage → 填回 input + toast
  //   - 写:input 变化 + 500ms 防抖
  //   - 清:send 成功后(走 clearInput wrapper)同步 removeItem
  const { loadOnMount, saveDraftEffect, clearDraft } = useDraft();
  useEffect(() => {
    loadOnMount(conversationIdProp, setInput);
    // 只在挂载时跑一次(hook 内部用 ref 自管)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => saveDraftEffect(input), [input, saveDraftEffect]);

  // === 单一发送入口 ===
  // clearInput 走自定义 wrapper:不仅 setInput(''),还同步清掉 localStorage
  // 草稿(否则 debounce 500ms 内 reload 会重新读回已发送的内容)。
  const send = useChatSend({
    wsConnected,
    getReadyState,
    getSessionId: () => sessionIdRef.current,
    send: sendFn,
    setIsLoading,
    setLastError,
    clearInput: () => {
      clearDraft();
      setInput('');
    },
    armWatchdog,
    pushUserAndPlaceholder: stream.pushUserAndPlaceholder,
  });

  // 顶层动作集成(键盘 / 速记 / 复制 / 重试)。
  const { handleKeyDown, insertPrompt, handleCopyMessage, handleRetry } =
    useChatAreaActions({
      inputRef,
      setInput,
      setIsLoading,
      setLastError: () => setLastError(null),
      send,
      stream,
      armWatchdog,
    });

  const isIdle = displayMessages.length === 0 && !isLoading;
  const composerPlaceholder = wsConnected
    ? '告诉 Nexus 你想完成什么'
    : connectionState === 'offline'
      ? '本地助手离线，请先在设置中检查模型'
      : '正在连接本地助手...';

  // === 停止当前流(2026-07-13 新增) ===
  // 客户端 gate:把 useChatStream 内部 stoppedRef 置 true,后续 chunk/thinking/final
  // 都被丢弃,不写 store;再在最后一条 assistant 末尾追加"已停止" marker 作为视觉
  // 反馈。同时 disarmWatchdog + setIsLoading(false),让 send 按钮重新可点。
  //
  // 为什么是"软停止"而不是断 WS:断 WS 会触发 wsConnected=false → useEffect onConnectedChange
  // 通知上游 → store.wsConnected 抖动 → 用户看到连接断开提示。客户端 gate 保留了
  // 同一个 WS,体感更平滑。代价:服务端 stream 继续跑到自然结束(后端无 abort 帧),
  // 但客户端不再处理其 chunk。
  const handleStop = useCallback(() => {
    stream.markUserStopped();
    // 立即写一个标记到当前 assistant 占位(appendToAssistant 已 gate,但 pushUserAndPlaceholder
    // 没 gate;这里直接调 setConversationMessages 绕开 stopped gate)
    const msgs = useStore.getState().conversationMessages;
    const last = msgs[msgs.length - 1];
    if (last && last.role === 'assistant') {
      const stoppedSuffix = last.content?.includes('[已停止]') ? '' : '\n\n_[已停止]_';
      useStore.getState().setConversationMessages([
        ...msgs.slice(0, -1),
        { ...last, content: (last.content ?? '') + stoppedSuffix },
      ]);
    }
    disarmWatchdog();
    setIsLoading(false);
  }, [stream, disarmWatchdog, setIsLoading]);

  return (
    <div className="chat-area">
      <div className="chat-scroll" ref={chatScrollRef}>
        {isIdle ? (
          <EmptyState onInsertPrompt={insertPrompt} />
        ) : (
          <MessageList
            messages={displayMessages}
            showThinking={showThinking}
            isLoading={isLoading}
            onCopy={handleCopyMessage}
            onRetry={handleRetry}
          />
        )}
        {userScrolledUp && (
          <button
            type="button"
            className="jump-to-bottom"
            onClick={() => scrollToBottom(true)}
            aria-label="跳到底部"
            title="跳到底部"
          >
            <span aria-hidden="true">↓</span> 跳到底部
          </button>
        )}
        {pendingClarification && (
          <ClarificationForm
            question={pendingClarification.question}
            options={pendingClarification.options}
            // 2026-07-13 修产品 bug:ClarificationForm onSubmit 直接调 send,但 send
            // 不动 pendingClarification 本地 state → 提交后 .clarify-card 残留渲染
            // (clarification.spec.ts 候选项 + 自由输入 2 个 case 都 fail)。Cancel
            // 路径已通过 onCancel 清,submit 路径必须同样清。理由:澄清回答是 send
            // 的一个分支,语义上"回答即关闭提问卡片"。
            onSubmit={(content: string) => {
              setPendingClarification(null);
              send(content);
            }}
            onCancel={() => setPendingClarification(null)}
          />
        )}
        {pendingConfirmation && (
          <ConfirmationCard
            interruptId={pendingConfirmation.interruptId}
            eventId={pendingConfirmation.eventId}
            actions={pendingConfirmation.actions}
            canSend={wsConnected && getReadyState() === 1}
            wsSend={sendFn}
            onResolved={() => setPendingConfirmation(null)}
          />
        )}
      </div>

      {lastError && (
        <div role="status" aria-live="assertive">
          <ErrorBanner
            lastError={lastError}
            onRetry={handleRetry}
            onClose={() => setLastError(null)}
          />
        </div>
      )}

      {/* 模型选择器 + 输入框容器 */}
      <div className="composer-input-group">
        <ModelSelector
          onOpenSettings={() => {
            window.dispatchEvent(new CustomEvent('nexus:open-preferences'));
          }}
        />
        <Composer
          value={input}
          onChange={setInput}
          onSubmit={() => send(input)}
          onKeyDown={handleKeyDown}
          placeholder={composerPlaceholder}
          disabled={!wsConnected}
          isLoading={isLoading}
          onStop={handleStop}
          inputRef={inputRef}
        />
      </div>
    </div>
  );
}

export default ChatArea;
