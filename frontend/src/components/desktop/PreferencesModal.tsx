import { useEffect, useRef, type JSX } from 'react';
import { useStore } from '../../store';
import { DEFAULT_MODEL } from '../../lib/config';

export type PreferencesTab = 'general';

export interface PreferencesModalProps {
  open: boolean;
  onClose: () => void;
}

export function PreferencesModal({ open, onClose }: PreferencesModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);

  const models = useStore((s) => s.models);
  const modelName = useStore((s) => s.modelName);
  const setModelName = useStore((s) => s.setModelName);
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const darkMode = useStore((s) => s.darkMode);
  const toggleDarkMode = useStore((s) => s.toggleDarkMode);

  const handleToggleDarkMode = () => toggleDarkMode();

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
            <select
              id="pref-model"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
            >
              {models.length === 0 ? (
                <option value={DEFAULT_MODEL}>{DEFAULT_MODEL} (推荐)</option>
              ) : (
                models.map((m) => (
                  <option key={m.id} value={m.name}>{m.name}</option>
                ))
              )}
            </select>
          </div>
          <div className="setting-row">
            <label>数据与隐私</label>
            <span className="setting-row-meta">本机保存 (~/.nexus/)</span>
          </div>
          <div className="setting-row">
            <label htmlFor="pref-thinking">显示思考过程</label>
            <button
              id="pref-thinking"
              type="button"
              className="setting-toggle"
              onClick={() => setShowThinking(!showThinking)}
              aria-pressed={showThinking}
            >
              {showThinking ? '已开启' : '已关闭'}
            </button>
          </div>
          <div className="setting-row">
            <label htmlFor="pref-dark">深色模式</label>
            <button
              id="pref-dark"
              type="button"
              className="setting-toggle"
              onClick={handleToggleDarkMode}
              aria-pressed={darkMode}
            >
              {darkMode ? '已开启' : '已关闭'}
            </button>
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
