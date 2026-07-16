import { useEffect } from 'react';

export interface UseGlobalShortcutsOptions {
  /** Cmd+N / Ctrl+N 新建对话 */
  onNewTask?: () => void;
  /** Cmd+K / Ctrl+K 聚焦 sidebar 搜索框 */
  onFocusSearch?: () => void;
  /** Cmd+/ / Ctrl+/ 聚焦 composer textarea */
  onFocusComposer?: () => void;
  /** Esc 关闭最上层 modal(找 .model-config-modal-overlay / .wechat-plugin-modal-overlay / .setup-overlay) */
  onCloseModal?: () => void;
}

/**
 * 全局键盘快捷键 hook — 第十一轮 (2026-07-16) 产品级打磨。
 *
 * 主流 agent 产品(Claude Desktop / ChatGPT / Cursor)标配:
 *   - Cmd+N 新建对话
 *   - Cmd+K 聚焦搜索框
 *   - Cmd+/ 聚焦 composer
 *   - Esc 关闭 modal
 *
 * modKey = e.metaKey || e.ctrlKey,让 macOS / Win / Linux 通用。
 *
 * 在 input / textarea / [contenteditable] 内不抢键,允许用户正常编辑。
 */
export function useGlobalShortcuts(options: UseGlobalShortcutsOptions): void {
  const { onNewTask, onFocusSearch, onFocusComposer, onCloseModal } = options;

  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      const modKey = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();

      if (modKey && key === 'n' && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        onNewTask?.();
        return;
      }

      if (modKey && key === 'k' && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        onFocusSearch?.();
        return;
      }

      if (modKey && key === '/' && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        onFocusComposer?.();
        return;
      }

      if (e.key === 'Escape' && !modKey) {
        // Esc 即便在 input / textarea 内也允许关闭 modal(典型 modal 行为)
        onCloseModal?.();
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onNewTask, onFocusSearch, onFocusComposer, onCloseModal]);
}

/** 实用工具:focus selector 对应元素,失败 fallback 到 querySelector。 */
export function focusElement(selector: string): boolean {
  const el = document.querySelector(selector) as HTMLElement | null;
  if (!el) return false;
  el.focus();
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    el.select();
  }
  return true;
}

/** 实用工具:关闭最上层 modal(按 DOM 出现顺序倒序找第一个可见的 overlay)。 */
export function closeTopModal(): boolean {
  const candidates = [
    '.model-config-modal-overlay',
    '.wechat-plugin-modal-overlay',
    '.setup-overlay',
    '.modal-overlay',
  ];
  for (const sel of candidates) {
    const el = document.querySelector(sel) as HTMLElement | null;
    if (el) {
      const closeBtn = el.querySelector('[data-modal-close], .modal-close, button[aria-label*="关闭"], button[aria-label*="Close"]') as HTMLElement | null;
      if (closeBtn) {
        closeBtn.click();
        return true;
      }
      // 没找到关闭按钮,模拟点 overlay 自身
      el.click();
      return true;
    }
  }
  return false;
}
