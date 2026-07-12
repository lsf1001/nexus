import type { StateCreator } from 'zustand';
import type { Message, Model } from '../../types';

/**
 * 主会话数据切片 — 业务数据,不持久化(Plan 4 §Phase 2)。
 *
 * 包括:
 * - conversationMessages:当前会话消息列表(由 ChatArea reducer 维护)
 * - models / currentModelId / modelName:模型选择(useBootstrap / ModelConfigModal 同步)
 * - isLoading:ChatArea 流式传输中状态(配合 useLoadingWatchdog 30s 清)
 *
 * 命名稳定:setter 名与原 useStore 完全一致(Plan 4 §Phase 5 迁移约束)。
 */
export interface ConversationsSlice {
  conversationMessages: Message[];
  models: Model[];
  currentModelId: string | null;
  modelName: string;
  isLoading: boolean;
  setConversationMessages: (messages: Message[]) => void;
  clearConversationMessages: () => void;
  setModels: (models: Model[]) => void;
  setCurrentModelId: (id: string | null) => void;
  setModelName: (name: string) => void;
  setIsLoading: (loading: boolean) => void;
}

export const createConversationsSlice: StateCreator<ConversationsSlice, [], [], ConversationsSlice> = (set) => ({
  conversationMessages: [],
  models: [],
  currentModelId: null,
  modelName: 'MiniMax-M3',
  isLoading: false,
  setConversationMessages: (messages) => set({ conversationMessages: messages }),
  clearConversationMessages: () => set({ conversationMessages: [] }),
  setModels: (models) => set({ models }),
  setCurrentModelId: (id) => set({ currentModelId: id }),
  setModelName: (name) => set({ modelName: name }),
  setIsLoading: (loading) => set({ isLoading: loading }),
});