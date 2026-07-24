/**
 * SkillsPanel 单测 — Round 1 SPEC §4.4。
 *
 * 契约:
 *   - 列出当前 project 的 skills(每行:名字 + 来源路径)
 *   - 切换 project → 重新加载列表
 *   - 后端失败 → 显示错误文案(不白屏)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { SkillsPanel } from '../SkillsPanel';

const fetchSkillsMock = vi.fn();

vi.mock('../../../lib/api', () => ({
  fetchSkills: (...args: unknown[]) => fetchSkillsMock(...args),
}));

describe('SkillsPanel', () => {
  beforeEach(() => {
    fetchSkillsMock.mockReset();
  });

  it('拉取并列出当前 project 的 skills', async () => {
    fetchSkillsMock.mockResolvedValueOnce([
      { name: 'code-review', path: '/x/code-review', source: 'local' },
      { name: 'seo-check', path: '/y/seo-check', source: 'project' },
    ]);
    const { container } = render(<SkillsPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelectorAll('.skills-panel-item').length).toBe(2);
    });
    expect(container.textContent).toContain('code-review');
    expect(container.textContent).toContain('seo-check');
  });

  it('fetchSkills 失败 → 显示错误文案', async () => {
    fetchSkillsMock.mockRejectedValueOnce(new Error('网络错误'));
    const { container } = render(<SkillsPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelector('.skills-panel-error')).not.toBeNull();
    });
  });

  it('projectId 变化时重新加载', async () => {
    fetchSkillsMock.mockResolvedValueOnce([
      { name: 'a', path: '/a', source: 'local' },
    ]);
    const { rerender } = render(<SkillsPanel projectId="p1" />);
    await waitFor(() => expect(fetchSkillsMock).toHaveBeenCalledWith('p1'));
    fetchSkillsMock.mockResolvedValueOnce([
      { name: 'b', path: '/b', source: 'project' },
    ]);
    rerender(<SkillsPanel projectId="p2" />);
    await waitFor(() => expect(fetchSkillsMock).toHaveBeenCalledWith('p2'));
  });
});
