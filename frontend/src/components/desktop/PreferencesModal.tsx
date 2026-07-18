import { useEffect, useRef, useState, type JSX } from 'react';
import { useStore } from '../../store';
import { DEFAULT_MODEL, DEFAULT_API_BASE } from '../../lib/config';
import { apiFetch } from '../../lib/api';
import { secretLength } from '../../lib/secret';

export interface PreferencesModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 设置弹窗 — 完整模型配置 + UI 偏好。
 *
 * 模型配置区块复用 SetupView 的保存逻辑(PUT /api/models/default),
 * 但以设置页形态呈现(不再是一次性向导)。用户可在首次配置后随时回来
 * 修改 API 地址 / 密钥 / 温度等参数。
 */
export function PreferencesModal({ open, onClose }: PreferencesModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);

  // === UI 偏好(来自 store) ===
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const darkMode = useStore((s) => s.darkMode);
  const toggleDarkMode = useStore((s) => s.toggleDarkMode);

  // === 模型配置(本地 state,打开时从后端加载) ===
  const [modelName, setModelName] = useState(DEFAULT_MODEL);
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [apiKey, setApiKey] = useState('');
  const [temperature, setTemperature] = useState('0.7');
  const [saveStatus, setSaveStatus] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingConfig, setIsLoadingConfig] = useState(false);

  // 打开时加载当前模型配置
  useEffect(() => {
    if (!open) return;
    if (dialogRef.current) dialogRef.current.focus();
    // 从后端拉取当前默认模型配置
    setIsLoadingConfig(true);
    apiFetch('/api/models/default')
      .then(async (res) => {
        if (res.ok) {
          const data = await res.json().catch(() => ({}));
          if (data.name) setModelName(data.name);
          if (data.api_base) setApiBase(data.api_base);
          if (data.api_key) setApiKey(data.api_key); // 后端可能返回掩码或空
          if (data.temperature != null) setTemperature(String(data.temperature));
        }
        // 404 = 尚未配置,保持默认值即可
      })
      .catch(() => { /* 离线/后端未启动,保持默认值 */ })
      .finally(() => setIsLoadingConfig(false));
  }, [open]);

  useEffect(() => {
    if (open && dialogRef.current) {
      dialogRef.current.focus();
    }
  }, [open]);

  const saveModelConfig = async () => {
    setIsSaving(true);
    setSaveStatus('正在保存...');

    try {
      const response = await apiFetch('/api/models/default', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: modelName,
          api_key: apiKey,
          api_base: apiBase,
          temperature: Number.parseFloat(temperature) || 0.7,
        }),
      });
      if (!response.ok) {
        const errText = (await response.text().catch(() => '')).trim();
        const reason = errText ? `: ${(errText.split('\n')[0] ?? '').slice(0, 120)}` : '';
        if (response.status === 401 || response.status === 403) {
          setSaveStatus(`鉴权失败${reason}`);
        } else if (response.status >= 500) {
          setSaveStatus(`后端异常(${response.status})${reason}`);
        } else {
          setSaveStatus(`保存失败(${response.status})${reason}`);
        }
        return;
      }
      setSaveStatus('已保存');
      setTimeout(() => setSaveStatus(''), 2500);
    } catch (_e) {
      setSaveStatus('网络错误,请检查后端');
    } finally {
      setIsSaving(false);
    }
  };

  if (!open) return null;

  const apiKeyLabel = apiKey ? `已设置(${secretLength(apiKey)}字符)` : '(未设置)';

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
        aria-label="设置"
        tabIndex={-1}
      >
        <header className="preferences-modal-header">
          <h2>设置</h2>
          <button
            type="button"
            className="preferences-modal-close"
            onClick={onClose}
            aria-label="关闭设置"
          >
            ✕
          </button>
        </header>

        <div className="preferences-modal-body">
          {/* ===== 模型配置区块 ===== */}
          <div className="settings-section">
            <div className="settings-section-title">模型配置</div>

            <div className="setting-row">
              <label htmlFor="set-model">模型</label>
              <input
                id="set-model"
                type="text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="如 MiniMax-M3、gpt-4o..."
              />
            </div>

            <div className="setting-row">
              <label htmlFor="set-api-base">API 地址</label>
              <input
                id="set-api-base"
                type="text"
                value={apiBase}
                onChange={(e) => setApiBase(e.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </div>

            <div className="setting-row">
              <label htmlFor="set-api-key">API 密钥</label>
              <div className="setting-input-group">
                <input
                  id="set-api-key"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="输入 API 密钥"
                />
                <span className="setting-input-hint">{apiKeyLabel}</span>
              </div>
            </div>

            <div className="setting-row">
              <label htmlFor="set-temp">温度参数</label>
              <input
                id="set-temp"
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                placeholder="0.0 ~ 1.0"
                style={{ maxWidth: '100px' }}
              />
            </div>

            <div className="setting-row setting-row-actions">
              <span className={`setting-status ${saveStatus.includes('失败') || saveStatus.includes('错误') ? 'is-error' : saveStatus === '已保存' ? 'is-ok' : ''}`}>
                {isLoadingConfig ? '加载中...' : saveStatus || '修改后点击保存'}
              </span>
              <button
                type="button"
                className="setting-btn-primary"
                onClick={saveModelConfig}
                disabled={isSaving}
              >
                {isSaving ? '保存中...' : '保存配置'}
              </button>
            </div>
          </div>

          {/* ===== UI 偏好区块 ===== */}
          <div className="settings-section">
            <div className="settings-section-title">界面</div>

            <div className="setting-row">
              <label htmlFor="set-thinking">显示思考过程</label>
              <button
                id="set-thinking"
                type="button"
                className="setting-toggle"
                onClick={() => setShowThinking(!showThinking)}
                aria-pressed={showThinking}
              >
                {showThinking ? '已开启' : '已关闭'}
              </button>
            </div>

            <div className="setting-row" style={{ borderBottom: 'none' }}>
              <label htmlFor="set-dark">深色模式</label>
              <button
                id="set-dark"
                type="button"
                className="setting-toggle"
                onClick={() => toggleDarkMode()}
                aria-pressed={darkMode}
              >
                {darkMode ? '已开启' : '已关闭'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
