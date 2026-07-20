/**
 * 模型选择器 — Claude 风格内联输入框选择器。
 *
 * 位置：Composer 输入框上方，作为输入区域的一部分。
 * 形态：
 *   - 触发器：紧凑行（模型图标 + 名称 + ▾），点击展开上浮面板。
 *   - 面板：富列表项（图标 + 名称 + 标签 + 价格倍率 + ✓）。
 *   - 顶部：Auto 选项。
 *   - 底部："配置自定义模型"（打开设置弹窗）。
 *
 * 数据源：store.models / modelName / currentModelId。
 * 切换：switchModel API → refreshModelsIntoStore 校正 store。
 */

import { useCallback, useEffect, useRef, useState, type JSX } from 'react';
import { useStore } from '../../store';
import { switchModel, refreshModelsIntoStore } from '../../lib/models';

/** 模型图标色板 — 按名称首字母/品牌分配固定色，保持稳定 */
const MODEL_COLORS: Record<string, string> = {
  H: '#3b82f6',   // Hy3 / 智谱蓝
  G: '#10b981',   // GLM 绿
  M: '#8b5cf6',   // MiniMax 紫
  K: '#f59e0b',   // Kimi 橙
  Z: '#ef4444',   // 通用红
};

function getModelColor(name: string): string {
  const first = (name?.[0] ?? 'Z').toUpperCase();
  return MODEL_COLORS[first] ?? '#6b7280';
}

function getModelInitial(name: string): string {
  return (name?.[0] ?? '?').toUpperCase();
}

export interface ModelSelectorProps {
  /** 点击"配置自定义模型"时的回调 */
  onOpenSettings?: () => void;
}

export function ModelSelector({ onOpenSettings }: ModelSelectorProps): JSX.Element | null {
  const models = useStore((s) => s.models);
  const currentModelId = useStore((s) => s.currentModelId);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const activeModel = models.find((m) => m.is_active) ?? models.find((m) => m.id === currentModelId) ?? models[0];

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  const handleSelect = useCallback(async (id: string): Promise<void> => {
    if (id === currentModelId) { setOpen(false); return; }
    setBusy(true);
    const res = await switchModel(id);
    if (res.ok) {
      await refreshModelsIntoStore().catch(() => {});
    }
    setBusy(false);
    setOpen(false);
  }, [currentModelId]);

  const handleSelectAuto = useCallback(async (): Promise<void> => {
    // Auto:选第一个有 api_key 的模型
    const firstValid = models.find((m) => m.api_key);
    if (firstValid) { await handleSelect(firstValid.id); }
    else { setOpen(false); }
  }, [models, handleSelect]);

  // 无模型可切换时隐藏触发器（0 或 1 个模型时仍显示当前模型名但不展开）
  if (models.length === 0) return null;

  return (
    <div className="model-picker" ref={containerRef}>
      {/* ===== 触发器 ===== */}
      <button
        type="button"
        className="model-picker-trigger"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={busy}
      >
        <span
          className="model-picker-icon"
          style={{ background: getModelColor(activeModel?.name ?? '') }}
        >
          {getModelInitial(activeModel?.name ?? '')}
        </span>
        <span className="model-picker-label">{activeModel?.name ?? '选择模型'}</span>
        <svg className="model-picker-caret" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* ===== 上浮面板 ===== */}
      {open && (
        <div className="model-picker-panel" role="listbox" aria-label="选择模型">
          {/* Auto 选项 */}
          <button
            type="button"
            className="model-picker-item model-picker-auto"
            role="option"
            onClick={() => { void handleSelectAuto(); }}
            disabled={busy}
          >
            <span className="model-picker-item-icon auto-icon">↻</span>
            <span className="model-picker-item-name">Auto</span>
          </button>

          {/* 分割线 */}
          <div className="model-picker-divider" />

          {/* 模型列表 */}
          {models.map((m) => {
            const isActive = m.id === currentModelId || m.is_active;
            const color = getModelColor(m.name);
            return (
              <button
                key={m.id}
                type="button"
                role="option"
                aria-selected={isActive}
                className={`model-picker-item ${isActive ? 'is-active' : ''}`}
                disabled={busy}
                onClick={() => { void handleSelect(m.id); }}
              >
                <span className="model-picker-item-icon" style={{ background: color }}>
                  {getModelInitial(m.name)}
                </span>
                <span className="model-picker-item-info">
                  <span className="model-picker-item-name">{m.name}</span>
                  {/* TODO: 后续从 model metadata 取 tag/price */}
                </span>
                <span className="model-picker-item-price">
                  {!m.api_key ? (
                    <span className="model-picker-badge no-key">未配置</span>
                  ) : (
                    '--'
                  )}
                </span>
                {isActive && (
                  <svg className="model-picker-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </button>
            );
          })}

          {/* 底部: 配置自定义模型 */}
          <div className="model-picker-divider" />
          <button
            type="button"
            className="model-picker-footer"
            onClick={() => { setOpen(false); onOpenSettings?.(); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
            </svg>
            配置自定义模型
          </button>
        </div>
      )}
    </div>
  );
}
