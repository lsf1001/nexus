/**
 * ChatArea 消息流状态 hook。
 *
 * 把原先散在 ChatArea function body 里的 messagesRef 同步 + setConversationMessages
 * 调用集中管理。Plan 2 §3 已指出 messagesRef mutate + setConversationMessages([...ref])
 * 的反模式:
 *   - messagesRef 是 ref(不触发 render),setConversationMessages 是 React 状态,
 *     两条路径并存容易让 ChatArea 的 render 与 ref 不同步(尤其 TypeScript 严格模式
 *     下 last 可能为 undefined)。
 *   - ref 引用问题:handleWsMessage / handleSend / handleRetry 都 push 到同一份 ref,
 *     ref 在 useEffect 中读 / 写但绕开 React 渲染,React DevTools 看不到。
 *
 * 这里把所有"消息列表的读写"集中到一组 callback,canonical state 仍在
 * useStore.conversationMessages(其它订阅者 / store 操作都依赖它),callback 通过
 * dispatch 表达意图(thinking / chunk / final / error / send / retry ...),
 * 同步通过 useStore.getState() 读最新值,保持 React 单向数据流。
 */

import { useCallback, useRef } from 'react';
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
  /** 在流式事件到达时,确保最后一条是 assistant 占位;返回是否新建了占位 */
  ensureAssistantPlaceholder: () => boolean;

  /** 把 chunk / thinking / final 追加到最后一条 assistant 消息;若没有 assistant 占位会先建 */
  appendToAssistant: (patch: Partial<Pick<Message, 'content' | 'thinking'>>) => void;

  /** 把 user 消息推入列表(等空 assistant 占位也一起推) */
  pushUserAndPlaceholder: (userMsg: Message) => void;

  /** 重试:删掉最后一条 assistant,推一个新的空 assistant 占位 */
  replaceAssistantWithPlaceholder: () => void;

  /** 清空全部(配合 resetTrigger / 新会话) */
  reset: () => void;

  /** 当前 React 状态里的消息快照(只读) */
  readonly snapshot: () => Message[];

  /** 用户主动停止流:appendToAssistant 后续调用 noop,直到下次 pushUserAndPlaceholder 清旗 */
  markUserStopped: () => void;

  /** 用户未主动停止,允许把流式 patch 写到 store(2026-07-13:为 handleFinal 暴露
   *  读路径,handleFinal 直接 setState 会绕过 appendToAssistant 的 stopped gate,
   *  导致"已停止" marker 被覆盖。handleFinal 在写入前查这个 gate。 */
  allowsStreaming: () => boolean;
}

export function useChatStream(): ChatStreamActions {
  // 真正的 canonical state 仍在 useStore.conversationMessages,
  // 这样 store 的 selector(`useStore((s) => s.conversationMessages)`)继续生效,
  // 其它订阅者(右侧消息列表 / 上下文预览)保持现有行为。reducer 占位已不需要,
  // 因为 setConversationMessages 已经会触发订阅者重渲染。
  //
  // user-stopped gate:用 ref 而非 store 状态 — 服务端流继续推 chunk/final/thinking,
  // 但客户端已"放弃"本条流。appendToAssistant 内部检查该 ref,true 直接 return,
  // 避免把"已停止"标记后的内容又渲染出来。新一轮 pushUserAndPlaceholder 时清旗,
  // 留空字符串 marker("已停止")在原 assistant 占位上,作为视觉信号。
  //
  // 为什么放 ref 不放 store:stop 是高频路径(chunk 每帧调一次),放 store 会触发
  // 全订阅者重渲染,放 ref 只在 read 路径生效,0 render。
  const stoppedRef = useRef(false);

  const ensureAssistantPlaceholder = useCallback((): boolean => {
    const msgs = useStore.getState().conversationMessages;
    const last = msgs[msgs.length - 1];
    if (!last || last.role !== 'assistant') {
      const placeholder: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        createdAt: new Date(),
      };
      useStore.getState().setConversationMessages([...msgs, placeholder]);
      return true;
    }
    return false;
  }, []);

  const appendToAssistant = useCallback(
    (patch: Partial<Pick<Message, 'content' | 'thinking'>>) => {
      // user-stopped gate:点 stop 后服务端流仍可能继续推 chunk/final/thinking,
      // 这里直接丢弃,不修改 store,避免"已停止"标记之后又冒出新文字。
      if (stoppedRef.current) return;
      const msgs = useStore.getState().conversationMessages;
      const idx = msgs.length - 1;
      if (idx < 0) return;
      const last = msgs[idx];
      if (!last || last.role !== 'assistant') return;
      const next: Message = { ...last };
      if (typeof patch.content === 'string') {
        next.content = (last.content ?? '') + patch.content;
      }
      if (typeof patch.thinking === 'string') {
        next.thinking = (last.thinking ?? '') + patch.thinking;
      }
      const cloned = [...msgs];
      cloned[idx] = next;
      useStore.getState().setConversationMessages(cloned);
    },
    [],
  );

  const pushUserAndPlaceholder = useCallback((userMsg: Message) => {
    // 新一轮对话 → 清 stopped gate,让后续 chunk 正常写入。
    stoppedRef.current = false;
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
    stoppedRef.current = false;
    useStore.getState().clearConversationMessages();
  }, []);

  const snapshot = useCallback(() => useStore.getState().conversationMessages, []);

  const markUserStopped = useCallback(() => {
    stoppedRef.current = true;
  }, []);

  const allowsStreaming = useCallback(() => !stoppedRef.current, []);

  return {
    ensureAssistantPlaceholder,
    appendToAssistant,
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
