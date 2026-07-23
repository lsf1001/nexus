import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useAppVersion } from '../../hooks/useAppVersion';
import type { Conversation } from '../../types';

export interface SidebarProps {
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  /** 重命名回调 — 双击 title 触发,Enter 提交,Esc 取消。后端 PUT 走 useConversationCrud。 */
  onRenameConversation: (id: string, title: string) => void | Promise<void>;
  onNewTask: () => void;
  onOpenPreferences?: () => void;
}

/** 删除二次确认按钮停留时长(ms),超时自动取消避免永久占位。 */
const DELETE_CONFIRM_TIMEOUT_MS = 5_000;

/**
 * 左侧栏 — 极简单栏。
 * 按 Nexus 实际功能设计：多会话 + 搜索 + 新对话 + 设置入口。
 * 记忆 / 工具 / 技能走 ⌘K 命令面板，不常驻侧栏（快捷键 Cmd/Ctrl+K，UI 无按钮入口）。
 *
 *   - 顶部：38px 拖拽区（让位 macOS traffic lights）
 *   - 品牌块：Logo N + Nexus
 *   - 搜索框（本地实时过滤）
 *   - + 新对话 按钮（Cmd+N / Ctrl+N 同样触发）
 *   - 会话列表（按 updatedAt 倒序，激活态左 3px 竖条）
 *   - 底部：设置入口 + 版本号
 *
 * 保留 .sidebar 根类与 .task-item / data-testid 等 e2e 选择器契约。
 */
export function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
  onNewTask,
  onOpenPreferences,
}: SidebarProps) {
  const [query, setQuery] = useState('');
  const toggleStarred = useStore((s) => s.toggleStarred);
  const starredIds = useStore((s) => s.starredIds);
  const appVersion = useAppVersion();

  const sortedConversations = useMemo(() => {
    const byUpdated = [...conversations].sort((a, b) => {
      const ta = new Date(a.updatedAt || a.createdAt.toISOString()).getTime();
      const tb = new Date(b.updatedAt || b.createdAt.toISOString()).getTime();
      return tb - ta;
    });
    // starred 排前(组内仍按 updatedAt 倒序)
    return byUpdated.sort((a, b) => {
      const aStar = starredIds.includes(a.id) ? 1 : 0;
      const bStar = starredIds.includes(b.id) ? 1 : 0;
      return bStar - aStar;
    });
  }, [conversations, starredIds]);

  const q = query.trim();
  const filteredConversations = useMemo(() => {
    if (!q) return sortedConversations;
    const lowerQ = q.toLowerCase();
    return sortedConversations.filter((conv) => {
      const title = conv.title || '新对话';
      if (title.toLowerCase().includes(lowerQ)) return true;
      return conv.messages.some((m) => (m.content || '').toLowerCase().includes(lowerQ));
    });
  }, [q, sortedConversations]);

  const renderTask = (conv: Conversation) => {
    const active = conv.id === currentConversationId;
    const title = conv.title || '新对话';
    const starred = starredIds.includes(conv.id);
    const handleSelect = (): void => onSelectConversation(conv);

    return (
      <TaskItem
        key={conv.id}
        conv={conv}
        title={title}
        active={active}
        starred={starred}
        onSelect={handleSelect}
        onDelete={onDeleteConversation}
        onRename={onRenameConversation}
        onToggleStar={() => toggleStarred(conv.id)}
      />
    );
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-drag" data-tauri-drag-region />

      <div className="sidebar-brand">
        <div className="sidebar-brand-mark">N</div>
        <span className="sidebar-brand-name">Nexus</span>
      </div>

      <div className="sidebar-section">
        <button
          className="btn-new-task"
          aria-label="新建对话 (快捷键 Cmd+N / Ctrl+N)"
          type="button"
          onClick={onNewTask}
        >
          <span className="plus-mark" aria-hidden="true">+</span>
          新对话
        </button>

        <input
          type="search"
          className="sidebar-search"
          placeholder="搜索对话"
          aria-label="搜索对话"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        {conversations.length === 0 ? (
          <div className="empty-tasks">
            <strong>还没有对话</strong>
            <span>点击"+ 新对话"开始</span>
            <button type="button" className="empty-tasks-cta" onClick={onNewTask}>
              + 开始新对话
            </button>
          </div>
        ) : filteredConversations.length === 0 ? (
          <div className="no-match">无匹配对话</div>
        ) : (
          <div className="recent-panel" aria-live="polite" aria-relevant="additions text">
            {filteredConversations.map(renderTask)}
          </div>
        )}
      </div>

      <div className="sidebar-footer">
        <button
          className="settings-trigger"
          aria-label="设置"
          type="button"
          onClick={onOpenPreferences}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span className="settings-trigger-label">设置</span>
        </button>
        <span className="sidebar-version">v{appVersion}</span>
      </div>
    </aside>
  );
}

/** 单条会话 — 拆出来便于把删除确认 + 重命名态各自管 state。 */
interface TaskItemProps {
  conv: Conversation;
  title: string;
  active: boolean;
  starred: boolean;
  onSelect: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void | Promise<void>;
  onToggleStar: () => void;
}

function TaskItem({
  conv,
  title,
  active,
  starred,
  onSelect,
  onDelete,
  onRename,
  onToggleStar,
}: TaskItemProps) {
  const [pendingDelete, setPendingDelete] = useState(false);
  const [renameState, setRenameState] = useState<
    { mode: 'editing'; draft: string } | { mode: 'idle' }
  >({ mode: 'idle' });

  // 删除确认超时自动取消 — 5s 内未点确定/取消就复位,避免误点永久占位。
  const deleteTimerRef = useRef<number | null>(null);
  useEffect(() => {
    if (!pendingDelete) return undefined;
    deleteTimerRef.current = window.setTimeout(() => {
      setPendingDelete(false);
    }, DELETE_CONFIRM_TIMEOUT_MS);
    return () => {
      if (deleteTimerRef.current !== null) {
        window.clearTimeout(deleteTimerRef.current);
        deleteTimerRef.current = null;
      }
    };
  }, [pendingDelete]);

  const handleRenameCommit = async (): Promise<void> => {
    if (renameState.mode !== 'editing') return;
    const next = renameState.draft.trim();
    if (!next || next === title) {
      setRenameState({ mode: 'idle' });
      return;
    }
    await onRename(conv.id, next);
    setRenameState({ mode: 'idle' });
  };

  const handleRenameCancel = (): void => {
    setRenameState({ mode: 'idle' });
  };

  const startRename = (): void => {
    setRenameState({ mode: 'editing', draft: title });
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className={`task-item ${active ? 'is-current' : ''} ${starred ? 'is-starred' : ''}`}
      onClick={() => {
        if (renameState.mode === 'editing') return;
        onSelect();
      }}
      onKeyDown={(event) => {
        if (renameState.mode === 'editing') return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect();
        }
      }}
      aria-current={active ? 'true' : undefined}
      aria-label={title}
    >
      <div
        className="task-item-body"
        onDoubleClick={(event) => {
          event.stopPropagation();
          startRename();
        }}
      >
        {renameState.mode === 'editing' ? (
          <input
            className="rename-input"
            type="text"
            value={renameState.draft}
            autoFocus
            onClick={(event) => event.stopPropagation()}
            onChange={(event) =>
              setRenameState({ mode: 'editing', draft: event.target.value })
            }
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                void handleRenameCommit();
              } else if (event.key === 'Escape') {
                event.preventDefault();
                handleRenameCancel();
              }
            }}
            onBlur={() => {
              void handleRenameCommit();
            }}
            aria-label={`重命名 ${title}`}
          />
        ) : (
          <strong>{title}</strong>
        )}
      </div>
      <div className="task-actions">
        <button
          type="button"
          aria-label={starred ? `取消星标 ${title}` : `星标 ${title}`}
          className={`star-btn ${starred ? 'is-starred' : ''}`}
          onClick={(event) => {
            event.stopPropagation();
            onToggleStar();
          }}
        >
          {starred ? '★' : '☆'}
        </button>
        {pendingDelete ? (
          <>
            <button
              type="button"
              aria-label={`确认删除 ${title}`}
              className="delete-confirm"
              data-testid={`delete-confirm-${conv.id}`}
              onClick={(event) => {
                event.stopPropagation();
                onDelete(conv.id);
                setPendingDelete(false);
              }}
            >
              确定?
            </button>
            <button
              type="button"
              aria-label={`取消删除 ${title}`}
              className="delete-cancel"
              onClick={(event) => {
                event.stopPropagation();
                setPendingDelete(false);
              }}
            >
              ×
            </button>
          </>
        ) : (
          <button
            aria-label={`删除对话 ${title}`}
            className="delete-btn"
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setPendingDelete(true);
            }}
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
