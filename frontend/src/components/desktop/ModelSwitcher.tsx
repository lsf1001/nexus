import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';
import { switchModel } from '../../lib/api';
import { useToastStore } from '../../store/useToast';

/**
 * 顶栏模型切换器 — 2026-07-16 第九轮 UI 重设计,2026-07-23 #22 接入后端真切。
 *
 * 形态:紧凑 chip(模型名 + ▾),点开下拉列表,点项切换 + 自动收起。
 * 数据源:`useStore.models` + `modelName`。
 *
 * 设计选择(#22 修订):
 * - 点列表项 → 调 `switchModel(id)` 走 `POST /api/models/switch`,后端重建 agent;
 *   成功 → store.setModelName + toast.success;失败 → 保留原 modelName + toast.error。
 * - 进行中 → chip 显示"切换中…",列表项 `aria-disabled`,避免双击 / 切到错的模型。
 *   dropdown 提前收起(setOpen(false)),loading 文案只露在 chip 上。
 * - 后端 `detail` 透传(已配置 API Key 缺失 / 模型不存在 / 配置无效),toast 文案
 *   包含"保留 X"以便用户看清回滚状态。
 */
export function ModelSwitcher() {
  const models = useStore((s) => s.models);
  const modelName = useStore((s) => s.modelName);
  const setModelName = useStore((s) => s.setModelName);
  const [open, setOpen] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
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

  const handleSelect = async (modelId: string, targetName: string): Promise<void> => {
    if (isSwitching) return;
    const previousName = modelName;
    setIsSwitching(true);
    setOpen(false);
    try {
      await switchModel(modelId);
      setModelName(targetName);
      useToastStore.getState().push('success', `已切换到 ${targetName}`, 2000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '切换失败';
      // setModelName 不动 → chip 自动回到 previousName
      useToastStore
        .getState()
        .push(
          'error',
          `切换失败: ${msg} (已保留 ${previousName || '原模型'})`,
          3500,
        );
    } finally {
      setIsSwitching(false);
    }
  };

  return (
    <div ref={containerRef} className="model-switcher">
      <button
        type="button"
        className="model-switcher-chip"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-busy={isSwitching}
        disabled={isSwitching}
        onClick={() => setOpen((v) => !v)}
        data-testid="model-switcher-chip"
      >
        <span className="model-switcher-name">
          {isSwitching ? '切换中…' : modelName || '选择模型'}
        </span>
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
                aria-disabled={isSwitching || undefined}
                className={`model-switcher-item ${isActive ? 'is-active' : ''}`}
                onClick={() => void handleSelect(m.id, m.name)}
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