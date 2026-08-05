import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useAppVersion } from '../../hooks/useAppVersion';
import type { Conversation } from '../../types';
import { ProjectDropdown } from './ProjectDropdown';
import { NewProjectDrawer } from './NewProjectDrawer';
import { ConversationMenu } from './ConversationMenu';
import { searchMessages, type SearchResult } from '../../lib/api';

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
/** 'all' 搜索 debounce(200ms 跟 GlobalSearchModal 一致 — 避免每按一键打后端)。 */
const SEARCH_DEBOUNCE_MS = 200;
/** 'all' 模式默认请求上限;后端 FTS5 上限 50/页(Round 3 Task 3.4)。 */
const SEARCH_ALL_LIMIT = 50;

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
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [menuState, setMenuState] = useState<
    { sessionId: string; anchor: { x: number; y: number } | null } | null
  >(null);
  const toggleStarred = useStore((s) => s.toggleStarred);
  const starredIds = useStore((s) => s.starredIds);
  const searchScope = useStore((s) => s.searchScope);
  const setSearchScope = useStore((s) => s.setSearchScope);
  const appVersion = useAppVersion();

  // 全部模式:'all' 时调 searchMessages,命中 session 集合用来排序 + 显示 snippet。
  const [allResults, setAllResults] = useState<SearchResult[]>([]);

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
  // 标题模式:只匹配 title — 列表接口不返 messages 正文,跨会话预取会爆内存。
  // 全部模式:调 searchMessages,q 非空时所有 conv 都参与渲染(不按命中过滤),
  // 命中会话通过 matchedSessionIds 提到前面 + 在 title 下渲染 snippet 摘要。
  const matchedSessionIds = useMemo(() => {
    if (searchScope !== 'all') return null;
    const set = new Set<string>();
    for (const r of allResults) set.add(r.session_id);
    return set;
  }, [searchScope, allResults]);

  const filteredConversations = useMemo(() => {
    if (!q) return sortedConversations;
    if (searchScope === 'title') {
      const lowerQ = q.toLowerCase();
      return sortedConversations.filter((conv) => {
        const title = conv.title || '新对话';
        return title.toLowerCase().includes(lowerQ);
      });
    }
    // 'all' — 全展示,matchedSessionIds 在渲染层排序前置
    return sortedConversations;
  }, [q, sortedConversations, searchScope]);

  // 全部模式:debounce 调 searchMessages;切换 scope/title 时清理。
  useEffect(() => {
    if (searchScope !== 'all') {
      setAllResults([]);
      return;
    }
    if (!q) {
      setAllResults([]);
      return;
    }
    const timer = window.setTimeout(() => {
      searchMessages(q, SEARCH_ALL_LIMIT)
        .then((resp) => setAllResults(resp.results))
        .catch(() => setAllResults([]));
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [q, searchScope]);

  // 第一段 snippet-by-session 映射(每个 session 只取第一条作为预览)。
  const snippetBySession = useMemo(() => {
    const map = new Map<string, SearchResult>();
    for (const r of allResults) {
      if (!map.has(r.session_id)) map.set(r.session_id, r);
    }
    return map;
  }, [allResults]);

  // 排序:命中在前(组内按 updatedAt),然后 starred,然后非命中。
  const orderedConversations = useMemo(() => {
    if (searchScope !== 'all' || !q || !matchedSessionIds) {
      return filteredConversations;
    }
    return [...filteredConversations].sort((a, b) => {
      const aHit = matchedSessionIds.has(a.id) ? 1 : 0;
      const bHit = matchedSessionIds.has(b.id) ? 1 : 0;
      if (aHit !== bHit) return bHit - aHit;
      const ta = new Date(a.updatedAt || a.createdAt.toISOString()).getTime();
      const tb = new Date(b.updatedAt || b.createdAt.toISOString()).getTime();
      return tb - ta;
    });
  }, [filteredConversations, matchedSessionIds, searchScope, q]);

  const renderTask = (conv: Conversation) => {
    const active = conv.id === currentConversationId;
    const title = conv.title || '新对话';
    const starred = starredIds.includes(conv.id);
    const handleSelect = (): void => onSelectConversation(conv);
    const showSnippet =
      searchScope === 'all' && q.length > 0 && snippetBySession.has(conv.id);
    const snippet = showSnippet ? snippetBySession.get(conv.id) : undefined;

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
        snippet={snippet}
        onOpenMenu={(anchor) => setMenuState({ sessionId: conv.id, anchor })}
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

      <ProjectDropdown onCreateProject={() => setNewProjectOpen(true)} />

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
          placeholder={searchScope === 'all' ? '搜索消息正文' : '搜索对话'}
          aria-label="搜索对话"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="sidebar-search-scope" role="group" aria-label="搜索作用域">
          <button
            type="button"
            data-scope="title"
            aria-pressed={searchScope === 'title'}
            className={`scope-btn ${searchScope === 'title' ? 'is-active' : ''}`}
            onClick={() => setSearchScope('title')}
          >
            标题
          </button>
          <button
            type="button"
            data-scope="all"
            aria-pressed={searchScope === 'all'}
            className={`scope-btn ${searchScope === 'all' ? 'is-active' : ''}`}
            onClick={() => setSearchScope('all')}
          >
            全部
          </button>
        </div>

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
            {orderedConversations.map(renderTask)}
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

      <NewProjectDrawer
        open={newProjectOpen}
        onClose={() => setNewProjectOpen(false)}
      />
      {menuState && (
        <ConversationMenu
          open
          sessionId={menuState.sessionId}
          anchor={menuState.anchor}
          onClose={() => setMenuState(null)}
          onDelete={(sid) => {
            onDeleteConversation(sid);
            setMenuState(null);
          }}
        />
      )}
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
  /** 'all' 模式下命中时,渲染首条 snippet(含 <mark> 高亮,后端 trusted output)。 */
  snippet?: SearchResult | undefined;
  /** 右键 / kebab 触发时把 anchor 透传给父组件,父组件渲染 <ConversationMenu>。 */
  onOpenMenu: (anchor: { x: number; y: number }) => void;
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
  snippet,
  onOpenMenu,
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
      data-conversation-id={conv.id}
      className={`task-item ${active ? 'is-current' : ''} ${starred ? 'is-starred' : ''} ${snippet ? 'has-match' : ''}`}
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
      onContextMenu={(event) => {
        event.preventDefault();
        onOpenMenu({ x: event.clientX, y: event.clientY });
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
          <>
            <strong>{title}</strong>
            {snippet && (
              <span
                className="search-snippet"
                dangerouslySetInnerHTML={{ __html: snippet.snippet }}
              />
            )}
          </>
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
