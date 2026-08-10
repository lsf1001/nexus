import { create } from 'zustand';

/**
 * GlobalSearchModal 全局开关 — Round 3 Task 3.4。
 *
 * 设计:⌘F 触发 useGlobalShortcuts → setOpen(true) → GlobalSearchModal open
 * 态保持在本 store,而 DesktopShell 只挂一次组件。这样跨路由(setup /
 * chat)快捷键都能唤起面板,不需要每个父组件各自 useState。
 *
 * 数据(results / query / loading)是组件内部状态,不需要 global — 因为
 * 每次 open 都要重置。把它们留组件内即可。
 */
interface GlobalSearchStore {
  isOpen: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export const useGlobalSearchStore = create<GlobalSearchStore>((set, get) => ({
  isOpen: false,
  setOpen: (open) => set({ isOpen: open }),
  toggle: () => set({ isOpen: !get().isOpen }),
}));