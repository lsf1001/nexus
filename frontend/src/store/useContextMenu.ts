import { create } from 'zustand';

export interface ContextMenuState {
  x: number;
  y: number;
  text: string;
  /** 显示在菜单上的标题（如"复制 消息" / "复制 任务"） */
  label?: string;
}

interface ContextMenuStore {
  menu: ContextMenuState | null;
  open: (state: ContextMenuState) => void;
  close: () => void;
}

/**
 * 全局右键菜单 store。任意页面通过 useContextMenuTrigger 触发，
 * 由 DesktopShell 顶层的 ContextMenuHost 渲染浮层。
 * 这样 1 个 menu 实例 + N 个 trigger,避免每个 page 自己维护状态。
 */
export const useContextMenu = create<ContextMenuStore>((set) => ({
  menu: null,
  open: (state) => set({ menu: state }),
  close: () => set({ menu: null }),
}));
