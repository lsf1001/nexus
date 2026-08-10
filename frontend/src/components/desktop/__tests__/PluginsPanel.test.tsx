/**
 * PluginsPanel 单测 — Round 5 Task 5.2。
 *
 * 契约:
 *   - 列出本地 plugins(name / version / description / type / path)
 *   - fetchPlugins 失败 → 显示错误文案(不白屏)
 *   - 后端返空数组 → 显示空态文案 + 路径提示
 *   - 与 SkillsPanel 差异:无 projectId 维度,本轮只读
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { PluginsPanel } from '../PluginsPanel';

const fetchPluginsMock = vi.fn();

vi.mock('../../../lib/api', () => ({
  fetchPlugins: (...args: unknown[]) => fetchPluginsMock(...args),
}));

describe('PluginsPanel', () => {
  beforeEach(() => {
    fetchPluginsMock.mockReset();
  });

  it('拉取并列出所有 plugin 字段', async () => {
    fetchPluginsMock.mockResolvedValueOnce({
      plugins: [
        {
          name: 'weather',
          version: '1.2.3',
          description: '天气查询插件',
          type: 'tool',
          path: '/home/u/.nexus/plugins/weather',
        },
        {
          name: 'trans',
          version: '0.0.1',
          description: '',
          type: 'hook',
          path: '/home/u/.nexus/plugins/trans',
        },
      ],
    });
    const { container } = render(<PluginsPanel />);
    await waitFor(() => {
      expect(container.querySelectorAll('.plugins-panel-item').length).toBe(2);
    });
    // name / version / description / type / path 都得渲染
    expect(container.textContent).toContain('weather');
    expect(container.textContent).toContain('v1.2.3');
    expect(container.textContent).toContain('天气查询插件');
    expect(container.textContent).toContain('tool');
    expect(container.textContent).toContain('/home/u/.nexus/plugins/weather');

    // 第二条 description 为空 → 不渲染 description 行
    const items = container.querySelectorAll('.plugins-panel-item');
    const secondDesc = items[1]?.querySelector('.plugins-panel-description');
    expect(secondDesc).toBeNull();
  });

  it('fetchPlugins 失败 → 显示错误文案', async () => {
    fetchPluginsMock.mockRejectedValueOnce(new Error('网络错误'));
    const { container } = render(<PluginsPanel />);
    await waitFor(() => {
      expect(container.querySelector('.plugins-panel-error')).not.toBeNull();
    });
    expect(container.textContent).toContain('网络错误');
  });

  it('后端返 401 → 错误文案含状态码', async () => {
    fetchPluginsMock.mockRejectedValueOnce(new Error('读取 plugins 失败: 401'));
    const { container } = render(<PluginsPanel />);
    await waitFor(() => {
      expect(container.querySelector('.plugins-panel-error')).not.toBeNull();
    });
    expect(container.textContent).toContain('401');
  });

  it('后端返空数组 → 显示空态文案 + 路径提示', async () => {
    fetchPluginsMock.mockResolvedValueOnce({ plugins: [] });
    const { container } = render(<PluginsPanel />);
    await waitFor(() => {
      expect(container.querySelector('.plugins-panel-empty')).not.toBeNull();
    });
    expect(container.querySelectorAll('.plugins-panel-item').length).toBe(0);
    expect(container.textContent).toContain('未发现 plugin');
    expect(container.textContent).toContain('~/.nexus/plugins/');
  });
});