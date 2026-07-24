/**
 * Skills 面板 — Round 1 SPEC §4.4。
 *
 * 列出当前 active project 的 skills;切 project 后 store.activeProjectId
 * 变 → 此组件重 mount(reload)。
 */
import { useEffect, useState } from 'react';
import { fetchSkills } from '../../lib/api';

interface SkillInfo {
  name: string;
  path: string;
  source: string;
}

export interface SkillsPanelProps {
  projectId: string;
}

export function SkillsPanel({ projectId }: SkillsPanelProps) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSkills(projectId)
      .then((data) => {
        if (!cancelled) {
          setSkills(data);
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
  if (skills.length === 0) {
    return <div className="skills-panel-empty">当前项目暂无 skills</div>;
  }
  return (
    <ul className="skills-panel-list">
      {skills.map((s) => (
        <li key={s.name} className="skills-panel-item">
          <span className="skills-panel-name">{s.name}</span>
          <span className="skills-panel-path">{s.path}</span>
          <span className={`skills-panel-source is-${s.source}`}>{s.source}</span>
        </li>
      ))}
    </ul>
  );
}
