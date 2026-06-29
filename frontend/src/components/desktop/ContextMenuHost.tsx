import { useEffect } from 'react';
import { useContextMenu } from '../../store/useContextMenu';
import { useToast } from '../../store/useToast';

/**
 * 全局"复制"菜单浮层。挂在 DesktopShell 顶层,只渲染一次。
 * 任意子组件通过 useContextMenuTrigger 打开/关闭。
 */
export function ContextMenuHost() {
  const menu = useContextMenu((s) => s.menu);
  const close = useContextMenu((s) => s.close);
  const toast = useToast();

  useEffect(() => {
    if (!menu) return;
    const handleDown = () => close();
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    const handleScroll = () => close();
    window.addEventListener('mousedown', handleDown);
    window.addEventListener('keydown', handleKey);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      window.removeEventListener('mousedown', handleDown);
      window.removeEventListener('keydown', handleKey);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [menu, close]);

  if (!menu) return null;

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const text = menu.text;
    close();
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      // 兜底：旧浏览器 / 非安全上下文
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    } catch (err) {
      toast.error(`复制失败: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <ul
      className="context-menu-floating"
      style={{ left: menu.x, top: menu.y }}
      role="menu"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <li>
        <button
          type="button"
          className="context-menu-item"
          onClick={handleCopy}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
          <span>复制{menu.label ? ` ${menu.label}` : ''}</span>
          <span className="kbd-hint">⌘C</span>
        </button>
      </li>
    </ul>
  );
}
