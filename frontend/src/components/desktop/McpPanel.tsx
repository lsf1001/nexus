/**
 * MCP 面板 — Round 1 SPEC §4.5。
 *
 * 与 SkillsPanel 同构;列 servers + tools 计数;切 project 触发重载。
 * 不实现 toggle(SPEC §6 列在第 5 轮范围)。
 */
import { useEffect, useState } from 'react';
import { fetchMcpToolsForProject, type McpToolsResponse } from '../../lib/api';

export interface McpPanelProps {
  projectId: string;
}

export function McpPanel({ projectId }: McpPanelProps) {
  const [data, setData] = useState<McpToolsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchMcpToolsForProject(projectId)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载失败');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <div className="mcp-panel-loading">加载中…</div>;
  if (error) return <div className="mcp-panel-error">{error}</div>;
  if (!data || data.servers.length === 0) {
    return <div className="mcp-panel-empty">当前项目暂无 MCP servers</div>;
  }
  return (
    <div className="mcp-panel">
      <div className="mcp-panel-summary">
        {data.server_count} servers · {data.tool_count} tools
      </div>
      <ul className="mcp-panel-list">
        {data.servers.map((s) => (
          <li key={s.name} className="mcp-panel-item">
            <span className="mcp-panel-name">{s.name}</span>
            <span className="mcp-panel-source">{s.source}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
