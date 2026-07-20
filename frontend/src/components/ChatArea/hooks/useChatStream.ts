/**
 * ChatArea 消息流操作 hook。
 *
 * 把原先散在 ChatArea function body 里的 messagesRef 同步 + setConversationMessages
 * 调用集中管理。Plan 2 §3 已指出 messagesRef mutate + setConversationMessages([...ref])
 * 的反模式,这里把所有"消息列表的读写"集中到一组 callback。
 *
 * 2026-07-20 重构:WS 流式 handler 不再走 ctx.stream 闭包链(handleChunk /
 * handleThinking 直接调 useStore.getState().appendAssistantPatch),所以本 hook
 * 的 appendToAssistant / ensureAssistantPlaceholder 不再被 wsHandlers 调用,
 * 仅保留 pushUserAndPlaceholder / markUserStopped / replaceAssistantWithPlaceholder
 * / reset / snapshot / allowsStreaming — 这些是用户主动交互路径(useChatSend /
 * ChatArea.handleStop / handleRetry)。
 *
 * stoppedRef 概念已升级为 store.streamingPaused(在 conversationsSlice 里),
 * handler / markUserStopped 共享同一份真值,React 多 render 闭包不会再丢失 gate。
 *
 * canonical state 仍在 useStore.conversationMessages,本 hook 通过调用
 * useStore.setState 写入。
 */

import { useCallback } from 'react';
import type { Message, StreamEvent } from '../../../types';
import { useStore } from '../../../store';

/**
 * ChatArea 派生操作集。
 *
 * 内部不直接持有 messages state — 通过 dispatch + 同步调用 useStore.setState 写
 * 会话历史,与原本 setConversationMessages([...ref]) 的"显式 broadcast 一次"
 * 行为保持兼容。
 */
export interface ChatStreamActions {
  /** 把 user 消息推入列表(等空 assistant 占位也一起推);同时清 streamingPaused gate。 */
  pushUserAndPlaceholder: (userMsg: Message) => void;

  /** 重试:删掉最后一条 assistant,推一个新的空 assistant 占位 */
  replaceAssistantWithPlaceholder: () => void;

  /** 清空全部(配合 resetTrigger / 新会话);同时清 streamingPaused gate。 */
  reset: () => void;

  /** 当前 React 状态里的消息快照(只读) */
  readonly snapshot: () => Message[];

  /** 用户主动停止流:set streamingPaused=true,后续 chunk / thinking / final 全 noop。 */
  markUserStopped: () => void;

  /** 用户未主动停止,允许把流式 patch 写到 store(2026-07-13:为 handleFinal 暴露
   *  读路径,handleFinal 直接 setState 会绕过 appendToAssistant 的 stopped gate,
   *  导致"已停止" marker 被覆盖。handleFinal 在写入前查这个 gate。 */
  allowsStreaming: () => boolean;
}

export function useChatStream(): ChatStreamActions {
  const pushUserAndPlaceholder = useCallback((userMsg: Message) => {
    // 新一轮对话 → 清 streamingPaused gate,让后续 chunk 正常写入。
    useStore.setState({ streamingPaused: false });
    const msgs = useStore.getState().conversationMessages;
    const placeholder: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
    };
    useStore.getState().setConversationMessages([...msgs, userMsg, placeholder]);
  }, []);

  const replaceAssistantWithPlaceholder = useCallback(() => {
    const msgs = useStore.getState().conversationMessages;
    const trimmed = msgs.slice(0, -1);
    const placeholder: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
    };
    useStore.getState().setConversationMessages([...trimmed, placeholder]);
  }, []);

  const reset = useCallback(() => {
    useStore.setState({ streamingPaused: false });
    useStore.getState().clearConversationMessages();
  }, []);

  const snapshot = useCallback(() => useStore.getState().conversationMessages, []);

  const markUserStopped = useCallback(() => {
    useStore.setState({ streamingPaused: true });
  }, []);

  const allowsStreaming = useCallback(() => !useStore.getState().streamingPaused, []);

  return {
    pushUserAndPlaceholder,
    replaceAssistantWithPlaceholder,
    reset,
    snapshot,
    markUserStopped,
    allowsStreaming,
  };
}

/**
 * 帮助函数:把 StreamEvent 转成 assistant 占位补丁(chunk / final / thinking)。
 *
 * 单独抽出避免 useWsMessageRouter 的 helper 函数过密。
 *   - type='chunk' / 'final' → content
 *   - type='thinking'         → thinking
 */
export function patchFromWsEvent(
  ev: StreamEvent,
): Partial<Pick<Message, 'content' | 'thinking'>> | null {
  if (ev.type === 'chunk' || ev.type === 'final') {
    return typeof ev.content === 'string' ? { content: ev.content } : null;
  }
  if (ev.type === 'thinking') {
    return typeof ev.content === 'string' ? { thinking: ev.content } : null;
  }
  return null;
}