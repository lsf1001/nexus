/**
 * 全局 Toast 抽象。
 *
 * 替代散落的 `console.warn` / `console.error`,让前端能在 UI 顶端浮层
 * 短暂提示用户"复制失败"、"会话同步失败"等非阻塞性问题。
 *
 * 用法:
 *   const toast = useToast();
 *   try { await copy(text); }
 *   catch (err) { toast.error(`复制失败: ${err.message}`); }
 *
 * 也支持组件外调用:
 *   toast.error('xxx')  // 不需要 hook,直接通过 useToastStore.getState()
 */

import { create } from 'zustand';

export type ToastKind = 'info' | 'success' | 'warn' | 'error';

export interface ToastItem {
  id: string;
  kind: ToastKind;
  message: string;
  /** 自动消失前的毫秒数,默认 3000。0 = 不自动消失。 */
  durationMs: number;
  /** 创建时间戳(毫秒),用于检测过期。 */
  createdAt: number;
}

interface ToastState {
  toasts: ToastItem[];
  push: (kind: ToastKind, message: string, durationMs?: number) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

let _seq = 0;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (kind, message, durationMs = 3000) => {
    const id = `t-${Date.now()}-${++_seq}`;
    const item: ToastItem = {
      id,
      kind,
      message,
      durationMs,
      createdAt: Date.now(),
    };
    set((s) => ({ toasts: [...s.toasts, item] }));
    if (durationMs > 0) {
      // 自动消失:用 setTimeout 而非 React 计时器,避免 toast 列表被卸载时计时器泄漏
      setTimeout(() => {
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
      }, durationMs);
    }
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

/** Hook 形式:在组件内调用 */
export function useToast() {
  const push = useToastStore((s) => s.push);
  const dismiss = useToastStore((s) => s.dismiss);
  return {
    info: (msg: string, durationMs?: number) => push('info', msg, durationMs),
    success: (msg: string, durationMs?: number) => push('success', msg, durationMs),
    warn: (msg: string, durationMs?: number) => push('warn', msg, durationMs),
    error: (msg: string, durationMs?: number) => push('error', msg, durationMs ?? 5000),
    dismiss,
  };
}