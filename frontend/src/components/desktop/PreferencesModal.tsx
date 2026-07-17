import { useEffect, useRef } from 'react';

export type PreferencesTab = 'general';

export interface PreferencesModalProps {
  open: boolean;
  onClose: () => void;
}

const MODEL_OPTIONS = [
  { value: 'MiniMax-M3', label: 'MiniMax-M3 (推荐)' },
  { value: 'MiniMax-M2', label: 'MiniMax-M2' },
  { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
];

export function PreferencesModal({ open, onClose }: PreferencesModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && dialogRef.current) {
      dialogRef.current.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay preferences-modal-overlay"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="preferences-modal"
        role="dialog"
        aria-modal="true"
        aria-label="偏好"
        tabIndex={-1}
      >
        <header className="preferences-modal-header">
          <h2>偏好</h2>
          <button
            type="button"
            className="preferences-modal-close"
            onClick={onClose}
            aria-label="关闭偏好"
          >
            ✕
          </button>
        </header>
        <div className="preferences-modal-body">
          <div className="setting-row">
            <label htmlFor="pref-model">当前模型</label>
            <select id="pref-model" defaultValue="MiniMax-M3">
              {MODEL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="setting-row">
            <label>数据与隐私</label>
            <span className="setting-row-meta">本机保存 (~/.nexus/)</span>
          </div>
          <div className="setting-row">
            <label htmlFor="pref-thinking">显示思考过程</label>
            <input id="pref-thinking" type="checkbox" defaultChecked />
          </div>
          <div className="setting-row">
            <label htmlFor="pref-dark">深色模式</label>
            <input id="pref-dark" type="checkbox" defaultChecked />
          </div>
          <div className="setting-row">
            <label>高级设置</label>
            <span className="setting-row-meta">稍后开放</span>
          </div>
        </div>
      </div>
    </div>
  );
}
