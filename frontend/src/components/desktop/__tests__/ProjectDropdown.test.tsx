/**
 * ProjectDropdown 单测 — Round 1 SPEC §4.3。
 *
 * 契约:
 *   - chip 显示 activeProject.display_name;无 active → "选择项目"
 *   - 点 chip → 展开列出所有 projects + "+ 新建项目" 项
 *   - 点列表项 → 调 setActiveProject(id) + 收起
 *   - 点 "+ 新建项目" → 调 onCreateProject 回调 + 收起
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { ProjectDropdown } from '../ProjectDropdown';
import type { Project } from '../../../store/slices/projects';

const setActiveProjectMock = vi.fn();
const loadProjectsMock = vi.fn();

vi.mock('../../../store/slices/projects', () => ({
  useProjects: () => ({
    projects: [
      { id: 'default', name: 'default', display_name: '默认项目', path: '/x' } as Project,
      { id: 'p1', name: 'p1', display_name: '我的博客', path: '/y' } as Project,
    ],
    activeProjectId: 'default',
    loading: false,
    setActiveProject: setActiveProjectMock,
    loadProjects: loadProjectsMock,
  }),
}));

describe('ProjectDropdown', () => {
  beforeEach(() => {
    setActiveProjectMock.mockReset();
    loadProjectsMock.mockReset();
  });

  it('chip 显示 active project display_name', () => {
    const { container } = render(<ProjectDropdown onCreateProject={vi.fn()} />);
    expect(container.querySelector('.project-dropdown-chip')?.textContent).toContain('默认项目');
  });

  it('点 chip → 展开列表(包含 "+ 新建项目")', () => {
    const { container } = render(<ProjectDropdown onCreateProject={vi.fn()} />);
    fireEvent.click(container.querySelector('.project-dropdown-chip') as HTMLElement);
    expect(container.querySelector('.project-dropdown-menu')).not.toBeNull();
    expect(container.querySelector('.project-dropdown-create')).not.toBeNull();
  });

  it('点列表项 → setActiveProject + 收起', async () => {
    const { container } = render(<ProjectDropdown onCreateProject={vi.fn()} />);
    fireEvent.click(container.querySelector('.project-dropdown-chip') as HTMLElement);
    fireEvent.click(container.querySelectorAll('.project-dropdown-item')[1] as HTMLElement);
    await waitFor(() => {
      expect(setActiveProjectMock).toHaveBeenCalledWith('p1');
      expect(container.querySelector('.project-dropdown-menu')).toBeNull();
    });
  });

  it('点 "+ 新建项目" → 调 onCreateProject', async () => {
    const onCreate = vi.fn();
    const { container } = render(<ProjectDropdown onCreateProject={onCreate} />);
    fireEvent.click(container.querySelector('.project-dropdown-chip') as HTMLElement);
    fireEvent.click(container.querySelector('.project-dropdown-create') as HTMLElement);
    await waitFor(() => {
      expect(onCreate).toHaveBeenCalled();
      expect(container.querySelector('.project-dropdown-menu')).toBeNull();
    });
  });
});