/**
 * Skills 面板 — Round 1 SPEC §4.4。
 *
 * 列出当前 active project 的 skills;切 project 后 store.activeProjectId
 * 变 → 此组件重 mount(reload)。
 *
 * 后端 `GET /api/skills` 返 `{project_id, skills[]}` 包装对象,与 MCP 端点
 * 结构对齐(Round 2 P0 修复)。
 */
import { useEffect, useState } from 'react';
import { fetchSkills, type SkillsResponse } from '../../lib/api';

export interface SkillsPanelProps {
  projectId: string;
}

export function SkillsPanel({ projectId }: SkillsPanelProps) {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSkills(projectId)
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

  if (loading) return <div className="skills-panel-loading">加载中…</div>;
  if (error) return <div className="skills-panel-error">{error}</div>;
  // 容错:后端万一返了不完整对象(缺 skills 字段)也不崩 — 走空态文案。
  const items = data?.skills ?? [];
  if (items.length === 0) {
    return <div className="skills-panel-empty">当前项目暂无 skills</div>;
  }
  return (
    <ul className="skills-panel-list">
      {items.map((s) => (
        <li key={s.name} className="skills-panel-item">
          <span className="skills-panel-name">{s.name}</span>
          <span className="skills-panel-path">{s.path}</span>
          <span className={`skills-panel-source is-${s.source}`}>{s.source}</span>
        </li>
      ))}
    </ul>
  );
}
