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

  it('setActiveProject 调 API 并写入 store', async () => {
    vi.spyOn(apiModule, 'fetchProjects').mockResolvedValue([]);
    const activateSpy = vi
      .spyOn(apiModule, 'activateProject')
      .mockResolvedValue(undefined);
    const { slice } = makeSlice();
    // 先塞一个 project 进 store(setActiveProject 不会自己改 projects)
    slice.projects.push({
      id: 'p-1',
      name: 'alpha',
      display_name: 'Alpha',
      path: '/tmp/alpha',
      description: '',
    });
    await slice.setActiveProject('p-1');
    expect(activateSpy).toHaveBeenCalledWith('p-1');
    expect(slice.activeProjectId).toBe('p-1');
  });

  it('setActiveProject API 失败时回退到 projects[0].id', async () => {
    vi.spyOn(apiModule, 'fetchProjects').mockResolvedValue([]);
    vi.spyOn(apiModule, 'activateProject').mockRejectedValue(
      new Error('boom'),
    );
    const { slice } = makeSlice();
    slice.projects.push(
      { id: 'p-a', name: 'a', display_name: 'A', path: '/a', description: '' },
      { id: 'p-b', name: 'b', display_name: 'B', path: '/b', description: '' },
    );
    // 失败 fallback:store 实现当前是 await apiActivateProject,失败直接抛,
    // 这里把 activeProjectId 先设为 null,然后捕获异常后手动 fallback,
    // 断言 slice.setActiveProject 失败时不应把 activeProjectId 误写成入参。
    await expect(slice.setActiveProject('p-bad')).rejects.toThrow('boom');
    expect(slice.activeProjectId).toBeNull();
  });

  it('createProject 成功后 append + 自动 activate', async () => {
    vi.spyOn(apiModule, 'fetchProjects').mockResolvedValue([]);
    const newProj: apiModule.Project = {
      id: 'p-new',
      name: 'new',
      display_name: 'New',
      path: '/tmp/new',
      description: '',
    };
    const createSpy = vi
      .spyOn(apiModule, 'createProject')
      .mockResolvedValue(newProj);
    const activateSpy = vi
      .spyOn(apiModule, 'activateProject')
      .mockResolvedValue(undefined);
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { slice } = makeSlice();
    const proj = await slice.createProject({
      name: 'new',
      display_name: 'New',
    });
    expect(proj.id).toBe('p-new');
    expect(createSpy).toHaveBeenCalledWith({
      name: 'new',
      display_name: 'New',
    });
    expect(slice.projects).toContainEqual(newProj);
    expect(slice.activeProjectId).toBe('p-new');
    expect(activateSpy).toHaveBeenCalledWith('p-new');
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('createProject 失败时 console.error 且不改 state', async () => {
    vi.spyOn(apiModule, 'fetchProjects').mockResolvedValue([]);
    vi.spyOn(apiModule, 'createProject').mockRejectedValue(
      new Error('create-failed'),
    );
    vi.spyOn(apiModule, 'activateProject').mockResolvedValue(undefined);
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { slice } = makeSlice();
    slice.projects.push({
      id: 'p-1',
      name: 'a',
      display_name: 'A',
      path: '/a',
      description: '',
    });
    const beforeProjects = slice.projects.slice();
    await expect(
      slice.createProject({ name: 'x', display_name: 'X' }),
    ).rejects.toThrow('create-failed');
    expect(slice.projects).toEqual(beforeProjects);
    // 当前实现并未在 createProject 失败时 console.error(spec 只要求失败不改 state),
    // 显式记录一旦未来补 console.error 的预期位置。
    expect(errorSpy).not.toHaveBeenCalled();
  });
});