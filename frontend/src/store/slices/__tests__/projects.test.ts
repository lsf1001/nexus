/**
 * ProjectsSlice 单测 — Round 1 SPEC §4.7。
 */
import { describe, expect, it, vi } from 'vitest';
import * as apiModule from '@/lib/api';
import { createProjectsSlice, type ProjectsSlice } from '../projects';

function makeSlice(): { slice: ProjectsSlice; setMock: ReturnType<typeof vi.fn>; state: ProjectsSlice } {
  const state: ProjectsSlice = {
    projects: [],
    activeProjectId: null,
    loading: false,
    loadProjects: () => Promise.resolve(),
    setActiveProject: () => Promise.resolve(),
    createProject: () => Promise.resolve({} as never),
  };
  const setMock = vi.fn((partial: Partial<ProjectsSlice> | ((s: ProjectsSlice) => Partial<ProjectsSlice>)) => {
    const update = typeof partial === 'function' ? partial(state) : partial;
    Object.assign(state, update);
  });
  const getMock = (): ProjectsSlice => state;
  // @ts-expect-error — vitest mock store 不需要完整 set 接口
  const slice = createProjectsSlice(setMock, getMock);
  Object.assign(state, slice);
  return { slice: state, setMock, state };
}

describe('ProjectsSlice', () => {
  it('initial', () => {
    const { slice } = makeSlice();
    expect(slice.activeProjectId).toBeNull();
  });

  it('loadProjects calls fetchProjects', async () => {
    const spy = vi.spyOn(apiModule, 'fetchProjects').mockResolvedValue([]);
    const { slice } = makeSlice();
    await slice.loadProjects();
    expect(spy).toHaveBeenCalled();
  });
});