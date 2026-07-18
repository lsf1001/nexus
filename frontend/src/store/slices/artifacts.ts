import type { StateCreator } from 'zustand';

/**
 * Artifacts 切片 — 右栏"作品"面板的数据源(Task 3.3)。
 *
 * Why 独立切片:Artifacts 是 agent 在 final / tool_result 帧中产出的
 * 结构化"作品"(code / markdown / svg / html),与对话消息流分离展示在
 * 右栏。它是运行时状态,不进 partialize 持久化(每次刷新重置为空)。
 *
 * 去重:pushArtifact 按 id 去重,重复 id 只保留第一条。id 由写入方
 * (wsHandlers.extractArtifact)生成;同一条 artifact 重复推送不会翻倍。
 */

export type ArtifactKind = 'code' | 'markdown' | 'svg' | 'html';

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  content: string;
  title?: string;
  /** code / markdown 的高亮语言(可选) */
  language?: string;
}

export interface ArtifactsSlice {
  artifacts: Artifact[];
  /** 按 id 去重追加一条 artifact(重复 id 忽略)。 */
  pushArtifact: (artifact: Artifact) => void;
  /** 清空当前会话的全部 artifact(切换会话 / 新任务时调用)。 */
  clearArtifacts: () => void;
}

export const createArtifactsSlice: StateCreator<
  ArtifactsSlice,
  [],
  [],
  ArtifactsSlice
> = (set) => ({
  artifacts: [],
  pushArtifact: (artifact) =>
    set((state) => {
      if (state.artifacts.some((a) => a.id === artifact.id)) return state;
      return { artifacts: [...state.artifacts, artifact] };
    }),
  clearArtifacts: () => set({ artifacts: [] }),
});
