/**
 * Project 切换 dropdown — Round 1 SPEC §4.3。
 *
 * 形态:紧凑 chip(project display_name + ▾),点开下拉列表,
 *      点项切 active + 自动收起;末尾"+ 新建项目"项调 onCreateProject 回调。
 *
 * 数据源:useProjects() — ProjectsSlice 的便利 hook,把 UI 关心的字段聚合成
 * 一个对象。点击 outside 关闭通过 document mousedown 事件 + containerRef 边界
 * 检测(没有 portal,菜单紧跟 chip)。
 */
import { useEffect, useRef, useState } from 'react';
import { useProjects, type Project } from '../../store/slices/projects';

export interface ProjectDropdownProps {
  onCreateProject: () => void;
}

export function ProjectDropdown({ onCreateProject }: ProjectDropdownProps) {
  const { projects, activeProjectId, setActiveProject } = useProjects();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const active = projects.find((p) => p.id === activeProjectId);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (ev: MouseEvent): void => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  return (
    <div ref={containerRef} className="project-dropdown">
      <button
        type="button"
        className="project-dropdown-chip"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid="project-dropdown-chip"
      >
        <span className="project-dropdown-name">
          {active?.display_name ?? '选择项目'}
        </span>
        <span aria-hidden="true" className="project-dropdown-caret">▾</span>
      </button>
      {open && (
        <ul className="project-dropdown-menu" role="listbox">
          {projects.map((p: Project) => (
            <li
              key={p.id}
              role="option"
              aria-selected={p.id === activeProjectId}
              className={`project-dropdown-item ${p.id === activeProjectId ? 'is-active' : ''}`}
              onClick={() => {
                setOpen(false);
                void setActiveProject(p.id);
              }}
            >
              {p.id === activeProjectId && (
                <span aria-hidden="true" className="project-dropdown-dot" />
              )}
              <span className="project-dropdown-item-name">{p.display_name}</span>
            </li>
          ))}
          <li
            className="project-dropdown-create"
            role="button"
            onClick={() => {
              setOpen(false);
              onCreateProject();
            }}
          >
            + 新建项目
          </li>
        </ul>
      )}
    </div>
  );
}