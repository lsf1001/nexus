import type { StateCreator } from 'zustand';
import { fetchMemory, type MemoryInfo } from '../../lib/api';

/**
 * 记忆切片 — 右栏"记忆"面板的数据源(2026-07-19 新增)。
 *
 * Why 独立切片:Nexus 的长期记忆是用户级 `~/.nexus/AGENTS.md` 文件(由
 * deepagents MemoryMiddleware 维护),前端通过 `GET /api/memory` 读取后
 * 展示。它是运行时状态,不进 partialize 持久化(每次刷新重置为空,重新拉取)。
 *
 * 与 Artifacts 切片平级,右栏通过 Tabs 切换两者。
 */

export interface MemorySlice {
  memory: MemoryInfo | null;
  memoryLoading: boolean;
  memoryError: string | null;
  /** 拉取长期记忆(幂等,缺失文件返回 exists=false 的空结构)。 */
  fetchMemory: () => Promise<void>;
}

export const createMemorySlice: StateCreator<
  MemorySlice,
  [],
  [],
  MemorySlice
> = (set) => ({
  memory: null,
  memoryLoading: false,
  memoryError: null,
  fetchMemory: async () => {
    set({ memoryLoading: true, memoryError: null });
    try {
      const info = await fetchMemory();
      set({ memory: info, memoryLoading: false });
    } catch (err) {
      set({
        memoryError: err instanceof Error ? err.message : '读取记忆失败',
        memoryLoading: false,
      });
    }
  },
});
