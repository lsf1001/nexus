import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';

/**
 * 顶栏模型切换器 — 2026-07-16 第九轮 UI 重设计。
 *
 * 形态:紧凑 chip(模型名 + ▾),点开下拉列表,点项切换 + 自动收起。
 * 数据源:`useStore.models` + `modelName`(store 单一真相源,
 * PreferencesModal 修改后此处即时反映)。
 *
 * 设计选择:
 * - 不再调 `/api/models/switch`:那是后端切换激活模型(重建 agent)的重操作;
 *   第九轮切模型只切前端 `modelName`(控制 prompt / 显示标签),
 *   若想真切换激活模型仍走设置页(SettingsView),跟主流 agent 桌面客户端一致。
 * - 点 chip 收起由 store 反向控制 + useEffect 处理外部 click 关闭。
 */
export function ModelSwitcher() {
  const models = useStore((s) => s.models);
  const modelName = useStore((s) => s.modelName);
  const setModelName = useStore((s) => s.setModelName);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // 外部 click 关闭 dropdown
  useEffect(() => {
    if (!open) return;
    const onDocClick = (ev: MouseEvent): void => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(ev.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const handleSelect = (next: string): void => {
    setModelName(next);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="model-switcher">
      <button
        type="button"
        className="model-switcher-chip"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid="model-switcher-chip"
      >
        <span className="model-switcher-name">{modelName || '选择模型'}</span>
        <span aria-hidden="true" className="model-switcher-caret">▾</span>
      </button>
      {open && models.length > 0 && (
        <ul className="model-switcher-dropdown" role="listbox">
          {models.map((m) => {
            const isActive = m.name === modelName;
            return (
              <li
                key={m.id}
                role="option"
                aria-selected={isActive}
                className={`model-switcher-item ${isActive ? 'is-active' : ''}`}
                onClick={() => handleSelect(m.name)}
              >
                {isActive && (
                  <span aria-hidden="true" className="model-switcher-dot" />
                )}
                <span className="model-switcher-item-name">{m.name}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
