/**
 * Zustand 顶层 store — 5 slice 合并 + persist + devtools。
 *
 * Plan 4 重构:从 useStore.ts 单 store 139 行拆出 4 slice(本轮不建 session
 * slice — `activeModelName` 在 useBootstrap 中是死代码,直接删)。各 slice
 * 文件见 ./slices/,跨切片派生见 ./selectors.ts(该文件已存在并导出 3 个 selector hook,当前全仓库无 import,属预留待接入)。
 *
 * 中间件:
 * - `persist` 只挂 uiPrefs 切片(partialize 显式列字段,防止业务字段被
 *   误写进 localStorage)。其它切片每次重置为初始值,避免 reload 后带
 *   着上次 session 的中间态(loading=true 永转 / 幽灵消息)。
 * - `devtools` 仅在开发模式生效(生产构建 tree-shake 掉)。
 *
 * 持久化 key:`nexus-preferences`(与原 useStore 一致,用户已有数据保留)。
 *
 * `skipHydration: true` 强制在 main.tsx 启动前 await rehydrateStore(),
 * 避免 React 19 + Vite HMR 下 store 引用被新创建时首屏 darkMode 仍为
 * 默认值的闪烁问题。
 */
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { createArtifactsSlice, type ArtifactsSlice } from './slices/artifacts';
import { createChannelsSlice, type ChannelsSlice } from './slices/channels';
import { createConversationsSlice, type ConversationsSlice } from './slices/conversations';
import { createMemorySlice, type MemorySlice } from './slices/memory';
import { createUiPrefsSlice, type UiPrefsSlice } from './slices/uiPrefs';
import { createWsStatusSlice, type WsStatusSlice } from './slices/wsStatus';

/** SSR / Electron 安全的 localStorage 包装,window 缺失或 quota 满都吞掉。 */
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

export type Store =
  UiPrefsSlice & WsStatusSlice & ConversationsSlice & ChannelsSlice & ArtifactsSlice & MemorySlice;

export const useStore = create<Store>()(
  persist(
    (...a) => ({
      ...createUiPrefsSlice(...a),
      ...createWsStatusSlice(...a),
      ...createConversationsSlice(...a),
      ...createChannelsSlice(...a),
      ...createArtifactsSlice(...a),
      ...createMemorySlice(...a),
    }),
    {
      name: 'nexus-preferences',
      storage: createJSONStorage(() => safeStorage),
      // 只持久化用户偏好;运行时状态每次重置为初始值
      partialize: (state) => ({
        darkMode: state.darkMode,
        showThinking: state.showThinking,
      }),
      skipHydration: true,
    }
  )
);

/**
 * 在 main.tsx 启动前先 rehydrate,这样首屏的 darkMode 已经是 localStorage
 * 的真值,useDarkModeRoot 第一次跑 effect 就拿到正确状态,不会有
 * light → dark 闪烁。
 */
export async function rehydrateStore(): Promise<void> {
  await useStore.persist.rehydrate();
}