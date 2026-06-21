import { useCallback } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { useContextMenu } from '../store/useContextMenu';

interface TriggerOptions {
  /** 菜单项 label 后缀,例如 "消息" / "任务" / "描述";为空时只显示"复制" */
  label?: string;
  /** 自定义菜单宽度（px），用于边界保护 */
  menuWidth?: number;
  /** 自定义菜单高度（px） */
  menuHeight?: number;
}

/**
 * 在任意元素 onContextMenu 调用: 阻止默认菜单,弹全局"复制"菜单。
 * 文本会被 trim,空文本不弹菜单（避免无意义弹窗）。
 */
export function useContextMenuTrigger(
  getText: (e: ReactMouseEvent) => string,
  options: TriggerOptions = {}
) {
  const open = useContextMenu((s) => s.open);

  return useCallback(
    (e: ReactMouseEvent) => {
      const text = getText(e).trim();
      if (!text) return;
      e.preventDefault();
      e.stopPropagation();
      const menuW = options.menuWidth ?? 180;
      const menuH = options.menuHeight ?? 44;
      const x = Math.min(e.clientX, window.innerWidth - menuW - 8);
      const y = Math.min(e.clientY, window.innerHeight - menuH - 8);
      open({ x, y, text, label: options.label });
    },
    [getText, open, options]
  );
}

/** 单纯基于固定文本的便捷 hook */
export function useCopyText(text: string | (() => string), label?: string) {
  return useContextMenuTrigger(
    typeof text === 'string' ? () => text : text,
    { label }
  );
}

/**
 * 非 hook 版本:用于在 .map() 回调内调用（hook 规则不允许在循环内调用 hook）。
 * 用法:onContextMenu={(e) => openContextMenuAt(e, "text", "label")}
 */
export function openContextMenuAt(
  e: ReactMouseEvent | { clientX: number; clientY: number; preventDefault: () => void; stopPropagation: () => void },
  text: string,
  label?: string
) {
  const trimmed = text.trim();
  if (!trimmed) return;
  e.preventDefault();
  e.stopPropagation();
  const menuW = 180;
  const menuH = 44;
  const x = Math.min(e.clientX, window.innerWidth - menuW - 8);
  const y = Math.min(e.clientY, window.innerHeight - menuH - 8);
  useContextMenu.getState().open({ x, y, text: trimmed, label });
}
