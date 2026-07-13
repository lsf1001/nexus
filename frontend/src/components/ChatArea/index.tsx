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
import { useAutoScroll } from './hooks/useAutoScroll';
import { useChatAreaActions } from './hooks/useChatAreaActions';
import { useChatSend } from './hooks/useChatSend';
import { type ChatStreamActions, useChatStream } from './hooks/useChatStream';
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
  activeConversationTitle = null,
  conversationCount = 0,
}: ChatAreaProps) {
  const [input, setInput] = useState('');
  const [lastError, setLastError] = useState<LastError | null>(null);
  const [pendingClarification, setPendingClarification] =
    useState<PendingClarification | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
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
  const modelName = useStore((s) => s.modelName);
  const pendingConfirmation = useStore((s) => s.pendingConfirmation);
  const setPendingConfirmation = useStore((s) => s.setPendingConfirmation);

  useEffect(() => {
    sessionIdRef.current = conversationIdProp;
  }, [conversationIdProp]);

  // === resetTrigger 同步状态 ===
  useEffect(() => {
    if (resetTrigger && resetTrigger > resetTriggerRef.current) {
      clearConversationMessages();
      setInput('');
      setPendingClarification(null);
      setPendingConfirmation(null);
      setLastError(null);
    }
    resetTriggerRef.current = resetTrigger ?? 0;
  }, [resetTrigger, clearConversationMessages, setPendingConfirmation]);

  // === 消息流操作(替代原 messagesRef mutate) ===
  const stream: ChatStreamActions = useChatStream();

  // === watchdog:30s 无终止帧强制清 loading ===
  const { arm: armWatchdog, disarm: disarmWatchdog } = useLoadingWatchdog({
    setIsLoading,
    setLastError,
  });

  // === WS 连接 — 鉴权走 subprotocol ===
  // 关键:WsRouterCtx 对象每次 render 都重算,会让 dispatcher(用 useCallback([ctx])
  // 记忆)每次都变 → useWsConnection 的 effect 会把它当 onMessage 变化,触发
  // 重连。修复:用 useMemo 包 ctx,稳定上游引用;useChatStream 的 callback
  // 内部都用 useCallback([...只读 store/state]),stream 引用稳定可入 deps。
  const wsCtx = useMemo<WsRouterCtx>(
    () => ({
      stream,
      setLastError,
      setIsLoading,
      setPendingClarification,
      setPendingConfirmation,
      disarmWatchdog,
      onSessionCreated,
    }),
    [stream, setLastError, setIsLoading, setPendingClarification, setPendingConfirmation, disarmWatchdog, onSessionCreated],
  );
  const handleWsMessage = useWsMessageRouter(wsCtx);

  const wsBase = getApiBase().replace(/^http/, 'ws');
  const wsUrl = `${wsBase}/api/ws`;
  const wsToken = getWsToken();
  const {
    connected: wsHookConnected,
    send: wsSend,
    getReadyState,
  } = useWsConnection({
    url: wsUrl,
    token: wsToken,
    onMessage: handleWsMessage,
  });

  const getReadyStateRef = useRef(getReadyState);
  getReadyStateRef.current = getReadyState;

  useEffect(() => {
    setWsConnected(wsHookConnected);
    onConnectedChange?.(wsHookConnected);
  }, [wsHookConnected, setWsConnected, onConnectedChange]);
  // 把下游 send 暴露给上游 input/textarea — 用 ref 桥避免每次 render 重建 sendRef
  const sendFn = useCallback(
    (msg: Parameters<typeof wsSend>[0]) => wsSend(msg),
    [wsSend],
  );

  // === 自动滚动(rAF) ===
  useAutoScroll({
    trigger: [displayMessages.length, isLoading],
    containerRef: messagesEndRef,
  });

  // === 单一发送入口 ===
  const send = useChatSend({
    wsConnected,
    getReadyState: getReadyStateRef.current,
    getSessionId: () => sessionIdRef.current,
    send: sendFn,
    setIsLoading,
    setLastError,
    clearInput: () => setInput(''),
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
      <div className="chat-scroll">
        {isIdle ? (
          <EmptyState
            modelName={modelName}
            connectionState={connectionState}
            activeConversationTitle={activeConversationTitle}
            conversationCount={conversationCount}
            onInsertPrompt={insertPrompt}
          />
        ) : (
          <MessageList
            messages={displayMessages}
            showThinking={showThinking}
            isLoading={isLoading}
            onCopy={handleCopyMessage}
          />
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
        <div ref={messagesEndRef} />
      </div>

      {lastError && (
        <ErrorBanner
          lastError={lastError}
          onRetry={handleRetry}
          onClose={() => setLastError(null)}
        />
      )}

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
  );
}

export default ChatArea;
