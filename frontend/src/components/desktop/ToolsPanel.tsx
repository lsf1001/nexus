import { useEffect, useState } from 'react';
import { useStore } from '../../store';
import {
  fetchMcpTools,
  type McpServerInfo,
  type McpToolInfo,
} from '../../lib/api';

/**
 * 工具面板 — 右栏"工具"Tab(2026-07-19)。
 *
 * 两块真实数据:
 *   1. MCP 工具: GET /api/mcp/tools 列出已连接服务器与加载到的工具。
 *   2. 调度活动: 从 store.conversationMessages 抽取所有 toolCall,
 *      实时反映 agent / 子代理的多步执行轨迹(状态 running/success/error)。
 *      这是 Nexus 子代理调度唯一的前端可视化入口,不造假遥测。
 */
export function ToolsPanel() {
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [tools, setTools] = useState<McpToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const conversationMessages = useStore((s) => s.conversationMessages);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchMcpTools()
      .then((data) => {
        if (!alive) return;
        setServers(data.servers);
        setTools(data.tools);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 实时调度轨迹:展平所有消息里的 toolCall
  const dispatchTrace = conversationMessages.flatMap((msg) =>
    (msg.toolCalls ?? []).map((tc) => ({
      id: tc.id,
      name: tc.name,
      state: tc.state,
    })),
  );
  const runningCount = dispatchTrace.filter((t) => t.state === 'running').length;

  return (
    <div className="tools-panel">
      <section className="tools-section">
        <div className="tools-section-head">
          <span>调度活动</span>
          {runningCount > 0 && <span className="tools-live">{runningCount} 进行中</span>}
        </div>
        {dispatchTrace.length === 0 ? (
          <p className="tools-empty">尚无工具调用。发送消息后,agent / 子代理的执行会实时出现在这里。</p>
        ) : (
          <ul className="dispatch-trace">
            {dispatchTrace.map((t) => (
              <li key={t.id} className={`dispatch-item state-${t.state}`}>
                <span className="dispatch-dot" />
                <span className="dispatch-name">{t.name}</span>
                <span className="dispatch-state">{t.state}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="tools-section">
        <div className="tools-section-head">
          <span>MCP 工具</span>
          <span className="tools-count">{tools.length}</span>
        </div>
        {loading ? (
          <p className="tools-empty">加载中...</p>
        ) : error ? (
          <p className="tools-error">工具加载失败:{error}</p>
        ) : tools.length === 0 ? (
          <p className="tools-empty">
            未连接任何 MCP 工具。在 <code>~/.nexus/mcp/config.json</code> 配置 MCP 服务器后重启生效。
          </p>
        ) : (
          <ul className="mcp-tool-list">
            {tools.map((t) => (
              <li key={t.name} className="mcp-tool-item">
                <code className="mcp-tool-name">{t.name}</code>
                {t.description && <span className="mcp-tool-desc">{t.description}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {servers.length > 0 && (
        <section className="tools-section">
          <div className="tools-section-head">
            <span>已配置服务器</span>
            <span className="tools-count">{servers.length}</span>
          </div>
          <ul className="mcp-server-list">
            {servers.map((s) => (
              <li key={s.name} className="mcp-server-item">
                <span className="mcp-server-name">{s.name}</span>
                <span className={`mcp-server-state ${s.enabled ? 'on' : 'off'}`}>
                  {s.enabled ? '启用' : '禁用'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
