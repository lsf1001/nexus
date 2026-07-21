import type { StateCreator } from 'zustand';

/**
 * 用户 UI 偏好切片 — 唯一持久化切片(主题 / thinking 显示 / 字号)。
 *
 * Why slice per concern:Plan 4 重构从 useStore.ts 139 行单 store 拆出;
 * 持久化只挂这个切片,partialize 显式只列 darkMode / showThinking / fontScale,
 * 防止业务字段(conversationMessages / channelInbox)被误写进 localStorage。
 *
 * 命名稳定:setter 名与原 useStore 完全一致(Plan 4 §Phase 5 迁移约束),
 * 所有现有 useStore 调用点不需改名。
 */
export type RightPanelTab = 'artifacts' | 'memory' | 'tools';

/**
 * 字号档 — useFontScaleRoot 把这值写到 :root 的 --fs var。
 * 三档线性 0.875 / 1 / 1.25(不取 1.5 是因为 40px × 1.5 = 60px 会让 hero 撞顶)。
 * FONT_SCALES 顺序即 Cmd+= 切换方向(+1)/ Cmd+- (-1)。
 */
export type FontScale = 0.875 | 1 | 1.25;
export const FONT_SCALES: readonly FontScale[] = [0.875, 1, 1.25] as const;
export const FONT_SCALE_LABEL: Record<FontScale, string> = {
  0.875: '小',
  1: '中',
  1.25: '大',
};

export interface UiPrefsSlice {
  darkMode: boolean;
  showThinking: boolean;
  /** 全局字号档(持久化于 localStorage,跨会话保留)。 */
  fontScale: FontScale;
  /** 右栏工作台当前 Tab(运行时态,不持久化)。 */
  rightPanelTab: RightPanelTab;
  /** 星标会话 id 集合(持久化于 localStorage,跨会话保留)。 */
  starredIds: string[];
  setDarkMode: (dark: boolean) => void;
  setShowThinking: (show: boolean) => void;
  toggleDarkMode: () => void;
  setFontScale: (s: FontScale) => void;
  /**
   * 循环切换字号档。delta ∈ {1, -1}: +1 → 大一档, -1 → 小一档;
   * 抵达边界(最小 0.875 / 最大 1.25)后保持不变。
   */
  cycleFontScale: (delta: 1 | -1) => void;
  setRightPanelTab: (tab: RightPanelTab) => void;
  toggleStarred: (id: string) => void;
}

export const createUiPrefsSlice: StateCreator<UiPrefsSlice, [], [], UiPrefsSlice> = (set) => ({
  darkMode: true,
  showThinking: true,
  fontScale: 1,
  rightPanelTab: 'memory',
  starredIds: [],
  setDarkMode: (dark) => set({ darkMode: dark }),
  setShowThinking: (show) => set({ showThinking: show }),
  toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
  setFontScale: (s) => set({ fontScale: s }),
  cycleFontScale: (delta) =>
    set((s) => {
      const idx = FONT_SCALES.indexOf(s.fontScale);
      const next = Math.max(0, Math.min(FONT_SCALES.length - 1, idx + delta));
      return { fontScale: FONT_SCALES[next]! };
    }),
  setRightPanelTab: (tab) => set({ rightPanelTab: tab }),
  toggleStarred: (id) =>
    set((s) => ({
      starredIds: s.starredIds.includes(id)
        ? s.starredIds.filter((x) => x !== id)
        : [...s.starredIds, id],
    })),
});