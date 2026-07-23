import { useEffect } from 'react';
import { useStore } from '../../../store';

export interface UseGlobalShortcutsOptions {
  /** Cmd+N / Ctrl+N 新建对话 */
  onNewTask?: () => void;
  /** Cmd+K / Ctrl+K 聚焦 sidebar 搜索框 */
  onFocusSearch?: () => void;
  /** Cmd+/ / Ctrl+/ 聚焦 composer textarea */
  onFocusComposer?: () => void;
  /** Esc 关闭最上层 modal(优先 .preferences-modal-overlay,其次 .model-config-modal-overlay / .wechat-plugin-modal-overlay / .setup-overlay) */
  onCloseModal?: () => void;
  /** Cmd+= / Cmd++ 字号大一档(不抢 input/textarea 焦点) */
  onZoomIn?: () => void;
  /** Cmd+- 字号小一档(不抢 input/textarea 焦点) */
  onZoomOut?: () => void;
  /** Cmd+0 字号复位(中档,1.0) */
  onZoomReset?: () => void;
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
 * 第十一轮(三栏重构,2026-07-20):
 *   - Cmd+\ / Ctrl+\ 折叠/展开右栏 Artifacts 面板
 *
 * 字号缩放(2026-07-21):Mac 浏览器风格的 Cmd+= / Cmd+- / Cmd+0 切三档字号
 * (在 user 集中反馈"Mac 快捷键 无法放大窗口及字体"后增加)。
 *
 * 第十一轮-3(2026-07-23,#9 键盘守卫):既有 4 个老快捷键(N/K/`/`/\)在
 * textarea/input/contenteditable 内也会被拦截,跟输入字符冲突(Cmd+N 是
 * textarea 高频快捷键 — 选词 / 移动到行首 / 操作系统级新建窗口等等;
 * Cmd+K 在 sidebar 搜索外也是高频编辑组合)。修复:所有 5 个 modKey 快捷
 * 键 + Cmd+\ 都加 isTextInput guard — focus 在文本输入元素内时,
 * e.preventDefault() 不调 + callback 不触发,让浏览器原生行为跑。
 *
 * 注意:hook docstring 之前声称"在 input / textarea / [contenteditable]
 * 内不抢键",实际 hook 从来没有这逻辑。本次才真正落实(2026-07-23)。
 *
 * modKey = e.metaKey || e.ctrlKey,让 macOS / Win / Linux 通用。
 */
export function useGlobalShortcuts(options: UseGlobalShortcutsOptions): void {
  const { onNewTask, onFocusSearch, onFocusComposer, onCloseModal, onZoomIn, onZoomOut, onZoomReset } = options;

  useEffect(() => {
    const isTextInput = (target: EventTarget | null): boolean => {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
    };

    const handler = (e: KeyboardEvent): void => {
      const modKey = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();
      const inTextInput = isTextInput(e.target);

      // 第十一轮-3(2026-07-23,#9 键盘守卫):modKey 快捷键在文本输入元素内
      // 放行,让浏览器原生行为跑(Cmd+N 在 textarea 不再被拦 → 不再"按 Cmd+N
      // 切到新会话结果 textarea 焦点被吞")。
      if (modKey && !e.altKey && !inTextInput) {
        if (key === 'n' && !e.shiftKey) {
          e.preventDefault();
          onNewTask?.();
          return;
        }
        if (key === 'k' && !e.shiftKey) {
          e.preventDefault();
          onFocusSearch?.();
          return;
        }
        if (key === '/' && !e.shiftKey) {
          e.preventDefault();
          onFocusComposer?.();
          return;
        }
        // Cmd+\ / Ctrl+\ 翻转右栏折叠态(SPEC §6)
        if (e.key === '\\' && !e.shiftKey) {
          e.preventDefault();
          useStore.getState().toggleArtifactsCollapsed();
          return;
        }
      }

      // 字号缩放:Cmd+= / Cmd++ / Cmd+- / Cmd+0 —— input focus 时放行。
      // 第十一轮-3 起所有 modKey 快捷键都共用 isTextInput guard(上面 if 块)。
      if (modKey && !e.altKey && !inTextInput) {
        if ((e.key === '=' || e.key === '+') && !e.shiftKey) {
          e.preventDefault();
          onZoomIn?.();
          return;
        }
        // shift 时 '+' 不再走 in(避免 Shift+Cmd+= 双触发)
        if (e.key === '-' && !e.shiftKey) {
          e.preventDefault();
          onZoomOut?.();
          return;
        }
        if (e.key === '0') {
          e.preventDefault();
          onZoomReset?.();
          return;
        }
      }

      if (e.key === 'Escape' && !modKey) {
        // Esc 即便在 input / textarea 内也允许关闭 modal(典型 modal 行为)
        onCloseModal?.();
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onNewTask, onFocusSearch, onFocusComposer, onCloseModal, onZoomIn, onZoomOut, onZoomReset]);
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

/** 实用工具:关闭最上层 modal(按 DOM 出现顺序倒序找第一个可见的 overlay)。
 *  顺序原则:层级高 / 打开晚的排前面,保证 Esc 优先关最外层。 */
export function closeTopModal(): boolean {
  const candidates = [
    '.command-palette-overlay',
    '.preferences-modal-overlay',
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
