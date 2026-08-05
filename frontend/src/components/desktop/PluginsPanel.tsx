/**
 * Round 5 Task 5.2:本地 Plugins 面板。
 *
 * 列出 ~/.nexus/plugins/<name>/plugin.json 扫描结果;纯只读,本轮
 * 不做安装/卸载/编辑(SPEC §6 第 5 轮范围外)。
 *
 * 与 SkillsPanel 的差异:
 *   - 无 projectId 维度(plugins 全局共享 ~/.nexus/plugins/)
 *   - 多展示 description / type badge
 */
import { useEffect, useState } from 'react';
import { fetchPlugins, type PluginManifest } from '../../lib/api';

export interface PluginsPanelProps {
  /** 保留 prop 占位,后续可能按 project 过滤;目前统一扫全局 */
  projectId?: string;
}

export function PluginsPanel(_props: PluginsPanelProps) {
  const [items, setItems] = useState<PluginManifest[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPlugins()
      .then((d) => {
        if (!cancelled) {
          setItems(d.plugins);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载失败');
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <div className="plugins-panel-loading">加载中…</div>;
  if (error) return <div className="plugins-panel-error">{error}</div>;
  if (!items || items.length === 0) {
    return (
      <div className="plugins-panel-empty">
        未发现 plugin。把 manifest 放到 <code>~/.nexus/plugins/&lt;name&gt;/plugin.json</code> 后刷新。
      </div>
    );
  }
  return (
    <ul className="plugins-panel-list">
      {items.map((p) => (
        <li key={p.name} className="plugins-panel-item">
          <div className="plugins-panel-row">
            <span className="plugins-panel-name">{p.name}</span>
            <span className="plugins-panel-version">v{p.version}</span>
            <span className={`plugins-panel-type is-${p.type}`}>{p.type}</span>
          </div>
          {p.description && (
            <div className="plugins-panel-description">{p.description}</div>
          )}
          <div className="plugins-panel-path">{p.path}</div>
        </li>
      ))}
    </ul>
  );
}