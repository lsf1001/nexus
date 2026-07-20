/**
 * 全局 Toast 浮层。
 *
 * 挂在 App 根部,监听 useToastStore.toasts,逐条渲染顶端浮层。
 * 容器 / item 样式迁 token:见 shell.css 的 .toast-host / .toast-item。
 * KIND_COLOR 4 种 kind 颜色保留 inline(动态 bg + border-left accent)。
 */

import { useToastStore, type ToastKind } from '../store/useToast';

interface KindColor {
  bg: string;
  border: string;
}

const KIND_COLOR: Record<ToastKind, KindColor> = {
  info: { bg: '#1f2937', border: '#3b82f6' },
  success: { bg: '#14532d', border: '#22c55e' },
  warn: { bg: '#78350f', border: '#f59e0b' },
  error: { bg: '#7f1d1d', border: '#ef4444' },
};

export function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-host">
      {toasts.map((t) => {
        const c = KIND_COLOR[t.kind] ?? KIND_COLOR.info;
        return (
          <div
            key={t.id}
            role="status"
            className="toast-item"
            style={{
              background: c.bg,
              borderLeft: `4px solid ${c.border}`,
            }}
            onClick={() => dismiss(t.id)}
            title="点击关闭"
          >
            {t.message}
          </div>
        );
      })}
    </div>
  );
}