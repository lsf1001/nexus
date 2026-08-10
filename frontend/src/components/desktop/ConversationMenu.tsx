/**
 * ConversationMenu — 单条会话的右键 / 长按 / kebab 菜单(Round 3 Task 3.5)。
 *
 * 菜单项:
 *   1. 复制 Session ID → navigator.clipboard.writeText(sessionId)
 *   2. 导出 Markdown → fetch /api/sessions/{id}/export.md → Blob → <a download>
 *   3. 创建分享链接 → POST /api/sessions/{id}/share → 弹窗显示 URL + 复制按钮
 *   4. 删除(已有的话复用,否则调 DELETE /api/sessions/{id})
 *
 * WHY 独立 modal:原 Sidebar TaskItem 只暴露删除按钮,Round 3 加导出 / 分享;
 * 再加两个按钮会撑爆 task-actions 行,改用 popover/menu 模式。
 *
 * anchor 坐标来自右键/长按事件 clientX/clientY,菜单绝对定位到此位置。
 * open=false 时不渲染,关闭由 onClose 回调驱动(点 overlay / Esc / 任一项完成)。
 */
import { useEffect, useRef, useState, type JSX } from 'react';
import { toast } from 'sonner';
import { apiFetch, resolveApiUrl } from '../../lib/api';

export interface ConversationMenuProps {
  open: boolean;
  sessionId: string;
  /** 菜单位置(浏览器坐标);原生右键用 clientX/clientY。 */
  anchor: { x: number; y: number } | null;
  onClose: () => void;
  onDelete: (sessionId: string) => void;
}

interface ShareResponse {
  token: string;
  url: string;
  expires_at: string;
}

export function ConversationMenu({
  open,
  sessionId,
  anchor,
  onClose,
  onDelete,
}: ConversationMenuProps): JSX.Element | null {
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // open 变化时重置 share 状态:关弹窗 → 清掉之前分享 URL。
  useEffect(() => {
    if (!open) {
      setShareUrl(null);
      setShareBusy(false);
      setExportBusy(false);
    }
  }, [open]);

  // Esc 关闭 + 点 overlay 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !anchor) return null;

  const handleCopyId = async (): Promise<void> => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(sessionId);
        toast.success('Session ID 已复制');
      } else {
        // 兜底:老浏览器 / 无 clipboard 权限 → 走 textarea + execCommand('copy')
        const textarea = document.createElement('textarea');
        textarea.value = sessionId;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        toast.success('Session ID 已复制');
      }
    } catch (err) {
      console.error('copy session id failed:', err);
      toast.error('复制失败');
    }
    onClose();
  };

  const handleExport = async (): Promise<void> => {
    setExportBusy(true);
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}/export.md`);
      if (!res.ok) {
        throw new Error(`导出失败: ${res.status}`);
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `session-${sessionId}.md`;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // 释放内存:revoke 推迟一帧,避免某些浏览器 click() 还没拿到 url 就 revoke
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 100);
      toast.success('Markdown 已下载');
    } catch (err) {
      console.error('export markdown failed:', err);
      toast.error('导出失败');
    } finally {
      setExportBusy(false);
      onClose();
    }
  };

  const handleShare = async (): Promise<void> => {
    setShareBusy(true);
    try {
      const res = await apiFetch(`/api/sessions/${sessionId}/share`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw new Error(`创建分享失败: ${res.status}`);
      }
      const data = (await res.json()) as ShareResponse;
      // share url 是 path-only,前端拼 origin 以便独立使用
      const absolute = resolveApiUrl(data.url);
      setShareUrl(absolute);
    } catch (err) {
      console.error('create share failed:', err);
      toast.error('创建分享链接失败');
    } finally {
      setShareBusy(false);
    }
  };

  const handleCopyShareUrl = async (): Promise<void> => {
    if (!shareUrl) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl);
        toast.success('分享链接已复制');
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = shareUrl;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        toast.success('分享链接已复制');
      }
    } catch (err) {
      console.error('copy share url failed:', err);
      toast.error('复制失败');
    }
  };

  const handleDelete = (): void => {
    onDelete(sessionId);
    onClose();
  };

  // 简单 anchor 定位:菜单固定宽 ~220px,避免溢出视口右/底;原 Sidebar 的
  // RecentPanel 不需要这种对齐,菜单是 overlay 浮层。
  const MENU_WIDTH = 220;
  const MENU_MAX_HEIGHT = 320;
  const left = Math.min(anchor.x, window.innerWidth - MENU_WIDTH - 8);
  const top = Math.min(anchor.y, window.innerHeight - MENU_MAX_HEIGHT - 8);

  return (
    <>
      {/* 透明 overlay — 拦截点击关菜单 */}
      <div
        className="conversation-menu-overlay"
        onClick={onClose}
        role="presentation"
        style={{ position: 'fixed', inset: 0, zIndex: 250 }}
      />
      <div
        ref={menuRef}
        className="conversation-menu"
        role="menu"
        aria-label="会话操作"
        style={{
          position: 'fixed',
          left,
          top,
          zIndex: 251,
          width: MENU_WIDTH,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {shareUrl === null ? (
          <>
            <button
              type="button"
              role="menuitem"
              data-action="copy-id"
              className="conversation-menu-item"
              onClick={() => {
                void handleCopyId();
              }}
            >
              复制 Session ID
            </button>
            <button
              type="button"
              role="menuitem"
              data-action="export"
              className="conversation-menu-item"
              disabled={exportBusy}
              onClick={() => {
                void handleExport();
              }}
            >
              {exportBusy ? '导出中…' : '导出 Markdown'}
            </button>
            <button
              type="button"
              role="menuitem"
              data-action="share"
              className="conversation-menu-item"
              disabled={shareBusy}
              onClick={() => {
                void handleShare();
              }}
            >
              {shareBusy ? '生成中…' : '创建分享链接'}
            </button>
            <div className="conversation-menu-sep" />
            <button
              type="button"
              role="menuitem"
              data-action="delete"
              className="conversation-menu-item is-danger"
              onClick={handleDelete}
            >
              删除会话
            </button>
          </>
        ) : (
          <div className="conversation-menu-share">
            <div className="conversation-menu-share-label">分享链接(7 天有效)</div>
            <div className="conversation-menu-share-url" title={shareUrl}>
              {shareUrl}
            </div>
            <div className="conversation-menu-share-actions">
              <button
                type="button"
                data-action="copy-share-url"
                className="conversation-menu-item"
                onClick={() => {
                  void handleCopyShareUrl();
                }}
              >
                复制
              </button>
              <button
                type="button"
                className="conversation-menu-item"
                onClick={onClose}
              >
                关闭
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}