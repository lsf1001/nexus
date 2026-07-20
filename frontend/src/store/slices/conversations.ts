import type { StateCreator } from 'zustand';
import type { Message, Model } from '../../types';
import { DEFAULT_MODEL } from '../../lib/config';

/**
 * 主会话数据切片 — 业务数据,不持久化(Plan 4 §Phase 2)。
 *
 * 包括:
 * - conversationMessages:当前会话消息列表(由 ChatArea reducer 维护)
 * - models / currentModelId / modelName:模型选择(useBootstrap 从 /api/models 载入)
 * - isLoading:ChatArea 流式传输中状态(配合 useLoadingWatchdog 30s 清)
 *
 * streamingPaused / appendAssistantContent / appendAssistantThinking 是 WS 流式
 * handler(handleChunk / handleThinking)的 action 入口(2026-07-20):
 *   - 把 stoppedRef gate + appendToAssistant 从 useChatStream useCallback 闭包
 *     搬到 store,handler 可直接 useStore.getState() 调用,不再依赖 ctx.stream,
 *     彻底消除"ctx 流每 render 重建导致 stream.appendToAssistant 闭包丢失"的 bug
 *   - appendAssistantContent 内部同时检查 streamingPaused gate(用户点 stop 后
 *     服务端继续推的 chunk / thinking 全部 noop,与原 useChatStream 行为等价)
 *
 * 命名稳定:setter 名与原 useStore 完全一致(Plan 4 §Phase 5 迁移约束)。
 */
export interface ConversationsSlice {
  conversationMessages: Message[];
  models: Model[];
  currentModelId: string | null;
  modelName: string;
  isLoading: boolean;
  /** 用户点 stop 后置 true;WS handler 写入前查这个 gate,防止"已停止"标记被覆盖。 */
  streamingPaused: boolean;
  setConversationMessages: (messages: Message[]) => void;
  clearConversationMessages: () => void;
  setModels: (models: Model[]) => void;
  setCurrentModelId: (id: string | null) => void;
  setModelName: (name: string) => void;
  setIsLoading: (loading: boolean) => void;
  /** 把 patch 写到 assistant 占位(自动检查 streamingPaused gate);无 placeholder 时建。 */
  appendAssistantPatch: (patch: { content?: string; thinking?: string }) => void;
  setStreamingPaused: (paused: boolean) => void;
}

export const createConversationsSlice: StateCreator<ConversationsSlice, [], [], ConversationsSlice> = (set, get) => ({
  conversationMessages: [],
  models: [],
  currentModelId: null,
  modelName: DEFAULT_MODEL,
  isLoading: false,
  streamingPaused: false,
  setConversationMessages: (messages) => set({ conversationMessages: messages }),
  clearConversationMessages: () => set({ conversationMessages: [] }),
  setModels: (models) => set({ models }),
  setCurrentModelId: (id) => set({ currentModelId: id }),
  setModelName: (name) => set({ modelName: name }),
  setIsLoading: (loading) => set({ isLoading: loading }),
  appendAssistantPatch: (patch) => {
    if (get().streamingPaused) return;
    const msgs = get().conversationMessages;
    const last = msgs[msgs.length - 1];
    // 没有 assistant 占位 → 建一个(content='',thinking='')保证 patch 有处写。
    if (!last || last.role !== 'assistant') {
      const placeholder: Message = {
        id: (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `m-${Date.now()}-${Math.random()}`,
        role: 'assistant',
        content: '',
        createdAt: new Date(),
      };
      const next: Message = { ...placeholder };
      if (typeof patch.content === 'string') next.content = patch.content;
      if (typeof patch.thinking === 'string') next.thinking = patch.thinking;
      set({ conversationMessages: [...msgs, next] });
      return;
    }
    const next: Message = { ...last };
    if (typeof patch.content === 'string') next.content = (last.content ?? '') + patch.content;
    if (typeof patch.thinking === 'string') next.thinking = (last.thinking ?? '') + patch.thinking;
    const cloned = [...msgs];
    cloned[cloned.length - 1] = next;
    set({ conversationMessages: cloned });
  },
  setStreamingPaused: (paused) => set({ streamingPaused: paused }),
});