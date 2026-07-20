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
export type RightPanelTab = 'artifacts' | 'memory' | 'tools';

export interface UiPrefsSlice {
  darkMode: boolean;
  showThinking: boolean;
  /** 右栏工作台当前 Tab(运行时态,不持久化)。 */
  rightPanelTab: RightPanelTab;
  /** 星标会话 id 集合(持久化于 localStorage,跨会话保留)。 */
  starredIds: string[];
  setDarkMode: (dark: boolean) => void;
  setShowThinking: (show: boolean) => void;
  toggleDarkMode: () => void;
  setRightPanelTab: (tab: RightPanelTab) => void;
  toggleStarred: (id: string) => void;
}

export const createUiPrefsSlice: StateCreator<UiPrefsSlice, [], [], UiPrefsSlice> = (set) => ({
  darkMode: true,
  showThinking: true,
  rightPanelTab: 'memory',
  starredIds: [],
  setDarkMode: (dark) => set({ darkMode: dark }),
  setShowThinking: (show) => set({ showThinking: show }),
  toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
  setRightPanelTab: (tab) => set({ rightPanelTab: tab }),
  toggleStarred: (id) =>
    set((s) => ({
      starredIds: s.starredIds.includes(id)
        ? s.starredIds.filter((x) => x !== id)
        : [...s.starredIds, id],
    })),
});