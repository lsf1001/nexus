import type { StateCreator } from 'zustand';

/**
 * Artifacts 切片 — 右栏"作品"面板的数据源(Task 3.3 / SPEC §4)。
 *
 * Why 独立切片:Artifacts 是 agent 在 final / tool_result 帧中产出的
 * 结构化"作品"(code / markdown / svg / html),与对话消息流分离展示在
 * 右栏。它是运行时状态,不进 partialize 持久化(每次刷新重置为空)。
 *
 * 去重:pushArtifact 按 id 去重,重复 id 只保留第一条。id 由写入方
 * (wsHandlers.extractArtifact / ToolCallCard)生成;同一条 artifact
 * 重复推送不会翻倍。
 *
 * 折叠(SPEC §2.2):collapsed 默认 true(右栏隐藏),ToolCallCard 联动
 * push 时自动 setCollapsed(false) 展开。
 */

export type ArtifactKind = 'code' | 'markdown' | 'svg' | 'html';

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  content: string;
  title?: string;
  /** code / markdown 的高亮语言(可选) */
  language?: string;
  /** 触发该产物的 tool_call.id(foot 显示来源) */
  sourceToolCallId?: string;
  /** 文件名/路径(可推断 kind / language) */
  filename?: string;
  /** 创建时间(ms epoch),可选 — 旧 caller 不传也能 push */
  createdAt?: number;
}

export interface ArtifactsSlice {
  artifacts: Artifact[];
  /** 当前激活 artifact.id(右栏显示哪一个),null = 显示空态 */
  activeArtifactId: string | null;
  /** 是否折叠(默认 true — 行为兼容旧两栏) */
  artifactsCollapsed: boolean;

  /** 按 id 去重追加一条 artifact;重复 id 忽略。 */
  pushArtifact: (artifact: Artifact) => void;
  /** 清空当前会话的全部 artifact(切换会话 / 新任务时调用)。 */
  clearArtifacts: () => void;
  /** 设置当前激活 artifact。 */
  setActiveArtifact: (id: string | null) => void;
  /** 删除指定 id 的 artifact;若删除的是 active 则 activeArtifactId 置 null。 */
  removeArtifact: (id: string) => void;
  /** 翻转折叠态。 */
  toggleArtifactsCollapsed: () => void;
  /** 显式设置折叠态。 */
  setArtifactsCollapsed: (collapsed: boolean) => void;
}

export const createArtifactsSlice: StateCreator<
  ArtifactsSlice,
  [],
  [],
  ArtifactsSlice
> = (set) => ({
  artifacts: [],
  activeArtifactId: null,
  artifactsCollapsed: true,

  pushArtifact: (artifact) =>
    set((state) => {
      if (state.artifacts.some((a) => a.id === artifact.id)) return state;
      return {
        artifacts: [...state.artifacts, artifact],
        // 新产物入栈时自动激活 + 展开(SPEC §4.2)
        activeArtifactId: artifact.id,
        artifactsCollapsed: false,
      };
    }),

  clearArtifacts: () =>
    set({ artifacts: [], activeArtifactId: null }),

  setActiveArtifact: (id) => set({ activeArtifactId: id }),

  removeArtifact: (id) =>
    set((state) => ({
      artifacts: state.artifacts.filter((a) => a.id !== id),
      activeArtifactId: state.activeArtifactId === id ? null : state.activeArtifactId,
    })),

  toggleArtifactsCollapsed: () =>
    set((state) => ({ artifactsCollapsed: !state.artifactsCollapsed })),

  setArtifactsCollapsed: (collapsed) => set({ artifactsCollapsed: collapsed }),
});