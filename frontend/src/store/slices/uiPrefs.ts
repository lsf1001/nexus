import type { StateCreator } from 'zustand';

/**
 * 用户 UI 偏好切片 — 唯一持久化切片(主题 / thinking 显示)。
 *
 * Why slice per concern:Plan 4 重构从 useStore.ts 139 行单 store 拆出;
 * 持久化只挂这个切片,partialize 显式只列 darkMode / showThinking,
 * 防止业务字段(conversationMessages / channelInbox)被误写进 localStorage。
 *
 * 命名稳定:setter 名与原 useStore 完全一致(Plan 4 §Phase 5 迁移约束),
 * 所有现有 useStore 调用点不需改名。
 */
export interface UiPrefsSlice {
  darkMode: boolean;
  showThinking: boolean;
  setDarkMode: (dark: boolean) => void;
  setShowThinking: (show: boolean) => void;
  toggleDarkMode: () => void;
}

export const createUiPrefsSlice: StateCreator<UiPrefsSlice, [], [], UiPrefsSlice> = (set) => ({
  darkMode: false,
  showThinking: true,
  setDarkMode: (dark) => set({ darkMode: dark }),
  setShowThinking: (show) => set({ showThinking: show }),
  toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
});