import { useEffect, useRef, useState, type JSX } from 'react';
import { DEFAULT_API_BASE } from '../../lib/config';
import {
  refreshModelsIntoStore,
  discoverProviderModels,
  importProviderModels,
  switchModel,
  deleteModel,
  type DiscoveredModel,
} from '../../lib/models';
import { useStore } from '../../store';
import { useAppVersion } from '../../hooks/useAppVersion';

export interface PreferencesModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 设置弹窗 — 只管理供应商配置 + 界面偏好 + 关于。模型选择已移至输入框
 * 上方（ModelSelector）。
 *
 * 三个区块用分割线清晰隔开：
 *   §1 PROVIDER — Base URL + API Key → 发现模型 → 导入全部
 *   §2 界面     — 思考模式 toggle + 深色模式 toggle
 *   §3 关于     — Nexus 版本号
 *
 * 模型选择已移至输入框上方（ModelSelector），设置弹窗只管理供应商配置。
 * 硬编码颜色：toggle 激活态用 #2563eb（蓝），不使用 CSS 变量，避免打包 APP 中失效。
 */
export function PreferencesModal({ open, onClose }: PreferencesModalProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);

  // === store: 界面偏好 ===
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const darkMode = useStore((s) => s.darkMode);
  const toggleDarkMode = useStore((s) => s.toggleDarkMode);
  const models = useStore((s) => s.models);
  const currentModelId = useStore((s) => s.currentModelId);
  const version = useAppVersion();

  // === 模型管理 ===
  const handleSwitchModel = async (id: string): Promise<void> => {
    await switchModel(id).catch(() => {});
    await refreshModelsIntoStore().catch(() => {});
  };
  const handleDeleteModel = async (id: string): Promise<void> => {
    if (typeof window !== 'undefined' && !window.confirm(`确认删除模型 ${id}?`)) return;
    await deleteModel(id).catch(() => {});
    await refreshModelsIntoStore().catch(() => {});
  };

  // === Provider 发现模型状态 ===
  const [providerBase, setProviderBase] = useState(DEFAULT_API_BASE);
  const [providerKey, setProviderKey] = useState('');
  const [discovered, setDiscovered] = useState<DiscoveredModel[]>([]);
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [discoverStatus, setDiscoverStatus] = useState('');
  const [keyError, setKeyError] = useState(false);

  // 打开时聚焦 + 重置状态
  useEffect(() => {
    if (!open) return;
    if (dialogRef.current) dialogRef.current.focus();
    setDiscoverStatus('');
    setDiscovered([]);
  }, [open]);

  if (!open) return null;

  // === Provider 发现 & 导入 ===
  const handleDiscover = async (): Promise<void> => {
    const url = providerBase.trim();
    const key = providerKey.trim();
    if (!url || !key) {
      setKeyError(!key);
      setDiscoverStatus(!url ? '请填写 Base URL' : '请填写 API Key');
      return;
    }
    setKeyError(false);
    setDiscoverBusy(true);
    setDiscoverStatus('正在连接 Provider...');
    setDiscovered([]);
    const res = await discoverProviderModels(url, key);
    if (!res.ok) {
      setDiscoverStatus(res.error || '发现失败');
      setDiscoverBusy(false);
      return;
    }
    setDiscovered(res.models);
    setDiscoverStatus(`发现 ${res.count} 个模型`);
    setDiscoverBusy(false);
  };

  const handleImport = async (): Promise<void> => {
    const url = providerBase.trim();
    const key = providerKey.trim();
    if (!url || !key) return;
    setDiscoverBusy(true);
    setDiscoverStatus('正在导入...');
    const res = await importProviderModels(url, key);
    if (!res.ok) {
      setDiscoverStatus(res.error || '导入失败');
      setDiscoverBusy(false);
      return;
    }
    await refreshModelsIntoStore().catch(() => {});
    setDiscoverStatus(`已导入 ${res.count} 个模型，可在输入框下方选择`);
    setDiscovered([]);
    setDiscoverBusy(false);
  };

  const isError = discoverStatus.includes('失败') || discoverStatus.includes('错误') || discoverStatus.includes('请');

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
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </header>

        <div className="preferences-modal-body">
          {/* ===== §1 PROVIDER ===== */}
          <div className="settings-section">
            <div className="settings-section-title">PROVIDER</div>
            <p className="provider-hint">
              填写 API 地址和密钥，自动发现并导入所有可用模型。
            </p>

            <div className="provider-form">
              <div className="setting-row">
                <label htmlFor="pv-base">Base URL</label>
                <input
                  id="pv-base"
                  type="text"
                  value={providerBase}
                  onChange={(e) => setProviderBase(e.target.value)}
                  placeholder="https://api.openai.com/v1"
                />
              </div>
              <div className="setting-row">
                <label htmlFor="pv-key">API Key</label>
                <input
                  id="pv-key"
                  type="password"
                  value={providerKey}
                  onChange={(e) => { setProviderKey(e.target.value); if (e.target.value.trim()) setKeyError(false); }}
                  placeholder="sk-..."
                  className={keyError ? 'is-error' : ''}
                />
              </div>
              <div className="provider-actions">
                <button
                  type="button"
                  className="setting-btn-primary"
                  onClick={() => { void handleDiscover(); }}
                  disabled={discoverBusy}
                >
                  {discoverBusy ? '连接中...' : '发现模型'}
                </button>
                {discovered.length > 0 && (
                  <button
                    type="button"
                    className="setting-btn-success"
                    onClick={() => { void handleImport(); }}
                    disabled={discoverBusy}
                  >
                    导入全部 ({discovered.length})
                  </button>
                )}
              </div>

              {discovered.length > 0 && (
                <div className="provider-discovered-list">
                  {discovered.map((dm) => (
                    <div key={dm.id} className="provider-model-item">
                      <span className="provider-model-id">{dm.id}</span>
                      {dm.owned_by && <span className="provider-model-owner">{dm.owned_by}</span>}
                    </div>
                  ))}
                </div>
              )}

              {discoverStatus && (
                <div className={`setting-status ${isError ? 'is-error' : ''}`}>
                  {discoverStatus}
                </div>
              )}
            </div>
          </div>

          {/* ===== §1.5 已导入模型 ===== */}
          <div className="settings-section settings-section-imported">
            <div className="settings-section-title">已导入模型</div>
            {models.length === 0 ? (
              <p className="provider-hint">尚未导入任何模型。先在上方发现并导入。</p>
            ) : (
              <div className="imported-model-list">
                {models.map((m) => {
                  const id = m.id;
                  const active = id === currentModelId;
                  return (
                    <div
                      key={id}
                      className={`imported-model-item ${active ? 'is-active' : ''}`}
                      title={active ? '当前激活模型' : '点击切换到此模型'}
                      onClick={() => { if (!active) void handleSwitchModel(id); }}
                      role="button"
                      tabIndex={0}
                    >
                      <span className="imported-model-name">{id}</span>
                      {active && <span className="imported-model-badge">激活</span>}
                      <button
                        type="button"
                        className="imported-model-delete"
                        aria-label={`删除 ${id}`}
                        onClick={(e) => { e.stopPropagation(); void handleDeleteModel(id); }}
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* ===== §2 界面 ===== */}
          <div className="settings-section settings-section-interface">
            <div className="settings-section-title">界面</div>
            <div className="setting-row">
              <div className="setting-row-label">
                <span className="setting-row-label-main">显示思考过程</span>
                <span className="setting-row-label-hint">展开模型的内部推理步骤</span>
              </div>
              <button
                type="button"
                className="setting-toggle"
                role="switch"
                aria-checked={showThinking}
                aria-pressed={showThinking}
                aria-label={showThinking ? '已开启' : '已关闭'}
                title="显示思考过程"
                onClick={() => setShowThinking(!showThinking)}
              />
            </div>
            <div className="setting-row">
              <div className="setting-row-label">
                <span className="setting-row-label-main">深色模式</span>
                <span className="setting-row-label-hint">使用暗色背景和浅色文字</span>
              </div>
              <button
                type="button"
                className="setting-toggle"
                role="switch"
                aria-checked={darkMode}
                aria-pressed={darkMode}
                aria-label={darkMode ? '已开启' : '已关闭'}
                title="深色模式"
                onClick={() => toggleDarkMode()}
              />
            </div>
          </div>

          {/* ===== §3 关于 ===== */}
          <div className="settings-section settings-section-about">
            <div className="settings-section-title">关于</div>
            <div className="about-version">Nexus v{version}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
