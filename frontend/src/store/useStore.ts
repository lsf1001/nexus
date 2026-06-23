import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ChannelType, Message, Model } from '../types';

/** 通道收件箱里的一条消息(独立于主会话,避免串台污染)。 */
export interface ChannelInboxMsg {
  id: string;
  user_id: string;
  content: string;
  timestamp: number;
}

interface AppState {
  isLoading: boolean;
  wsConnected: boolean;
  showThinking: boolean;
  modelName: string;
  models: Model[];
  currentModelId: string | null;
  darkMode: boolean;
  conversationMessages: Message[];
  /**
   * 通道收件箱:按 channelType 分桶,与主会话消息隔离。
   * 取代旧的 wechatInbox: Message[],支持多通道 (wechat/feishu/telegram)。
   */
  channelInbox: Record<string, ChannelInboxMsg[]>;

  setIsLoading: (loading: boolean) => void;
  setWsConnected: (connected: boolean) => void;
  setShowThinking: (show: boolean) => void;
  setModelName: (name: string) => void;
  setModels: (models: Model[]) => void;
  setCurrentModelId: (id: string | null) => void;
  setDarkMode: (dark: boolean) => void;
  setConversationMessages: (messages: Message[]) => void;
  clearConversationMessages: () => void;
  addChannelInbox: (channelType: ChannelType, msg: ChannelInboxMsg) => void;
  clearChannelInbox: (channelType: ChannelType) => void;
}

// 持久化用户偏好(darkMode / showThinking),刷新后保留。运行时状态
// (isLoading / wsConnected / conversationMessages / channelInbox)不持久化,
// 否则 reload 后会带着上一次 session 的中间态(loading=true 永转、幽灵消息)。
// 安全的 localStorage 访问:Electron / 浏览器 / SSR 都不会因 window 缺失而崩。
const safeStorage = {
  getItem: (key: string): string | null => {
    try {
      return typeof window !== 'undefined' ? window.localStorage.getItem(key) : null;
    } catch {
      return null;
    }
  },
  setItem: (key: string, value: string): void => {
    try {
      if (typeof window !== 'undefined') window.localStorage.setItem(key, value);
    } catch {
      /* quota or private mode */
    }
  },
  removeItem: (key: string): void => {
    try {
      if (typeof window !== 'undefined') window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      isLoading: false,
      wsConnected: false,
      showThinking: true,
      modelName: 'MiniMax-M3',
      models: [],
      currentModelId: null,
      darkMode: false,
      conversationMessages: [],
      channelInbox: {},

      setIsLoading: (loading) => set({ isLoading: loading }),
      setWsConnected: (connected) => set({ wsConnected: connected }),
      setShowThinking: (show) => set({ showThinking: show }),
      setModelName: (name) => set({ modelName: name }),
      setModels: (models) => set({ models }),
      setCurrentModelId: (id) => set({ currentModelId: id }),
      setDarkMode: (dark) => set({ darkMode: dark }),
      setConversationMessages: (messages) => set({ conversationMessages: messages }),
      clearConversationMessages: () => set({ conversationMessages: [] }),
      addChannelInbox: (channelType, msg) =>
        set((state) => ({
          channelInbox: {
            ...state.channelInbox,
            [channelType]: [...(state.channelInbox[channelType] ?? []), msg],
          },
        })),
      clearChannelInbox: (channelType) =>
        set((state) => ({
          channelInbox: { ...state.channelInbox, [channelType]: [] },
        })),
    }),
    {
      name: 'nexus-preferences',
      storage: createJSONStorage(() => safeStorage),
      // 只持久化用户偏好;运行时状态每次重置为初始值
      partialize: (state) => ({
        darkMode: state.darkMode,
        showThinking: state.showThinking,
      }),
      // 关键:React 19 下 zustand persist 自动 rehydrate 在 Vite dev 里偶发
      // 不可靠(初始化时 store.darkMode 仍是 false,后续 setDarkMode 不会
      // 触发 useDarkModeRoot effect 重跑,因为 Vite HMR 注入的 store 引用
      // 已经是新创建)。强制 skipHydration + 在 main.tsx 里 await rehydrate,
      // 确保首屏拿到的是 localStorage 里的真值。
      skipHydration: true,
    }
  )
);

// 在 main.tsx 启动前先 rehydrate,这样首屏的 darkMode 已经是 localStorage 的真值,
// useDarkModeRoot 第一次跑 effect 就拿到正确状态,不会有 light → dark 的闪烁。
// 暴露给 main.tsx 用。
export async function rehydrateStore(): Promise<void> {
  await useStore.persist.rehydrate();
}
