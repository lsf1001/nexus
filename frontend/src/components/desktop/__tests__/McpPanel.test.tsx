/**
 * McpPanel 单测 — Round 1 SPEC §4.5。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { McpPanel } from '../McpPanel';

const fetchMcpToolsForProjectMock = vi.fn();

vi.mock('../../../lib/api', () => ({
  fetchMcpToolsForProject: (...args: unknown[]) => fetchMcpToolsForProjectMock(...args),
}));

describe('McpPanel', () => {
  beforeEach(() => {
    fetchMcpToolsForProjectMock.mockReset();
  });

  it('列出当前 project 的 MCP servers', async () => {
    fetchMcpToolsForProjectMock.mockResolvedValueOnce({
      project_id: 'p1',
      servers: [{ name: 'x', source: '/x.json' }, { name: 'y', source: '/y.json' }],
      tools: [],
      tool_count: 0,
      server_count: 2,
    });
    const { container } = render(<McpPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelectorAll('.mcp-panel-item').length).toBe(2);
    });
  });

  it('失败 → 错误文案', async () => {
    fetchMcpToolsForProjectMock.mockRejectedValueOnce(new Error('加载失败'));
    const { container } = render(<McpPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelector('.mcp-panel-error')).not.toBeNull();
    });
  });
});
