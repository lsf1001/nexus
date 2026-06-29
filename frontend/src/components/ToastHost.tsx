/**
 * 全局 Toast 浮层。
 *
 * 挂在 App 根部,监听 useToastStore.toasts,逐条渲染顶端浮层。
 * 不引入额外 UI 库 — 简单 inline style 即可覆盖 4 种 kind。
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
    <div
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => {
        const c = KIND_COLOR[t.kind] ?? KIND_COLOR.info;
        return (
          <div
            key={t.id}
            role="status"
            style={{
              background: c.bg,
              borderLeft: `4px solid ${c.border}`,
              color: '#f9fafb',
              padding: '10px 14px',
              borderRadius: 6,
              minWidth: 240,
              maxWidth: 400,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              pointerEvents: 'auto',
              cursor: 'pointer',
              fontSize: 13,
              lineHeight: 1.4,
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