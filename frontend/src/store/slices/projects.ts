/**
 * ProjectsSlice — Round 1 SPEC §4.7。
 *
 * 状态:projects 列表 + 当前 active project id。
 * 副作用:loadProjects / setActiveProject / createProject 均调后端 REST,
 * 并通过 activateProject 把 active_project_id 落盘到 ~/.nexus/active_project.json。
 *
 * useProjects 是一个把 slice 状态聚合到单一对象的便利 hook,方便
 * ProjectDropdown 等 UI 组件在一次解构里拿到全部字段。Zustand 5 的
 * selector 引用稳定性规则:每次渲染函数返回的对象是新的,会触发订阅重渲。
 * 因此实现采用"4 个单字段 selector + 浅聚合"模式 — 每个字段独立订阅,
 * 聚合时不会因单个字段变化而让无关消费者重渲。
 */
import type { StateCreator } from 'zustand';
import {
  activateProject as apiActivateProject,
  createProject as apiCreateProject,
  fetchProjects,
  type CreateProjectInput,
  type Project,
} from '@/lib/api';
import { useStore } from '../../store';

export interface ProjectsSlice {
  projects: Project[];
  activeProjectId: string | null;
  loading: boolean;
  loadProjects: () => Promise<void>;
  setActiveProject: (id: string) => Promise<void>;
  createProject: (input: CreateProjectInput) => Promise<Project>;
}

export const createProjectsSlice: StateCreator<ProjectsSlice, [], [], ProjectsSlice> = (set, get) => ({
  projects: [],
  activeProjectId: null,
  loading: false,

  loadProjects: async () => {
    set({ loading: true });
    try {
      const projects = await fetchProjects();
      set({
        projects,
        activeProjectId: get().activeProjectId ?? projects[0]?.id ?? null,
        loading: false,
      });
    } catch (err) {
      set({ loading: false });
      throw err;
    }
  },

  setActiveProject: async (id: string) => {
    await apiActivateProject(id);
    set({ activeProjectId: id });
  },

  createProject: async (input: CreateProjectInput) => {
    const proj = await apiCreateProject(input);
    set((s) => ({
      projects: [...s.projects, proj],
      activeProjectId: proj.id,
    }));
    try {
      await apiActivateProject(proj.id);
    } catch {
      // 切 active 失败不阻断,UI 已是新 project
    }
    return proj;
  },
});

/**
 * 便利 hook — 把 ProjectsSlice 上 UI 关心的字段聚合成一个对象。
 * 单字段 selector + 直接 return,每次渲染新建对象是预期行为(消费方会
 * 用 useMemo / 解构 useProjects 结果,且 ProjectDropdown 在 mounted 时
 * 调用一次,不放在高频路径上)。
 */
export function useProjects(): Pick<
  ProjectsSlice,
  'projects' | 'activeProjectId' | 'loading' | 'loadProjects' | 'setActiveProject'
> {
  const projects = useStore((s) => s.projects);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const loading = useStore((s) => s.loading);
  const loadProjects = useStore((s) => s.loadProjects);
  const setActiveProject = useStore((s) => s.setActiveProject);
  return { projects, activeProjectId, loading, loadProjects, setActiveProject };
}