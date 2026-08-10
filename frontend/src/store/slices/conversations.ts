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
/** 搜索作用域:'title' 只匹配 title(默认);'all' 走 /api/search/messages。 */
export type SearchScope = 'title' | 'all';

export interface ConversationsSlice {
  conversationMessages: Message[];
  models: Model[];
  currentModelId: string | null;
  modelName: string;
  isLoading: boolean;
  /** 用户点 stop 后置 true;WS handler 写入前查这个 gate,防止"已停止"标记被覆盖。 */
  streamingPaused: boolean;
  /** Sidebar 搜索作用域(Round 3 Task 3.5):title 仅本地匹配;all 走后端 FTS5。 */
  searchScope: SearchScope;
  setConversationMessages: (messages: Message[]) => void;
  clearConversationMessages: () => void;
  setModels: (models: Model[]) => void;
  setCurrentModelId: (id: string | null) => void;
  setModelName: (name: string) => void;
  setIsLoading: (loading: boolean) => void;
  /** 把 patch 写到 assistant 占位(自动检查 streamingPaused gate);无 placeholder 时建。 */
  appendAssistantPatch: (patch: { content?: string; thinking?: string }) => void;
  /** 2026-08-08 Round 6.2:error 帧到达时清理末尾 assistant 占位,防止 placeholder leak。
   *  - 末尾是空占位(content==='' && !thinking):直接 pop(用户没看过,零信息损失)
   *  - 末尾是 thinking-only 占位(用户看见过思考痕迹):content 改写为 errorText,
   *    thinking 保留(产品反馈"上一轮没拿到回复,思考过程是 X"),不再泄漏到下一轮
   *  - 末尾已经有 content / 不是 assistant:不动 */
  discardEmptyAssistantPlaceholder: (errorText: string) => void;
  setStreamingPaused: (paused: boolean) => void;
  setSearchScope: (scope: SearchScope) => void;
}

export const createConversationsSlice: StateCreator<ConversationsSlice, [], [], ConversationsSlice> = (set, get) => ({
  conversationMessages: [],
  models: [],
  currentModelId: null,
  modelName: DEFAULT_MODEL,
  isLoading: false,
  streamingPaused: false,
  searchScope: 'title',
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
  discardEmptyAssistantPlaceholder: (errorText) => {
    const state = get();
    // 与 appendAssistantPatch 的 streamingPaused gate 行为一致:用户点 stop
    // 之后,后续 chunk/thinking/final 全 noop;error 帧也应当尊重,不去清理
    // 占位 — 否则会把 handleStop 留下的 [已停止] marker 抹掉。
    // 下一轮 pushUserAndPlaceholder 进来时先 setStreamingPaused(false),自然
    // 走新 placeholder 替换旧占位的路径。
    if (state.streamingPaused) return;
    const msgs = state.conversationMessages;
    const last = msgs[msgs.length - 1];
    if (!last || last.role !== 'assistant') return;
    const empty = last.content === '' || last.content === undefined;
    const noThinking = !last.thinking || last.thinking.length === 0;
    if (empty && noThinking) {
      set({ conversationMessages: msgs.slice(0, -1) });
      return;
    }
    if (empty) {
      const next = [...msgs];
      next[next.length - 1] = { ...last, content: errorText };
      set({ conversationMessages: next });
    }
  },
  setSearchScope: (scope) => set({ searchScope: scope }),
});