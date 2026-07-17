import type { JSX } from 'react';
import type { Conversation } from '../../types';

export interface SidebarProps {
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
}

/**
 * 左侧栏 — 第十四轮:高保真 Claude Desktop 极简版
 *   - 无品牌块、无 +新对话按钮、无搜索 input、无 section 标题、无微信底栏
 *   - 顶部 38px 让位 macOS traffic lights
 *   - task-item 扁平列表,当前态左 3px 竖条
 *   - 底部一行 Nexus v1.3.0 版本号
 */
export function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onDeleteConversation,
  onNewTask,
}: SidebarProps): JSX.Element {
  const sortedConversations = [...conversations].sort((a, b) => {
    const ta = new Date(a.updatedAt || a.createdAt).getTime();
    const tb = new Date(b.updatedAt || b.createdAt).getTime();
    return tb - ta;
  });

  const renderTask = (conv: Conversation): JSX.Element => {
    const active = conv.id === currentConversationId;
    const updated = new Date(conv.updatedAt || conv.createdAt);
    const title = conv.title || '新对话';

    const handleSelect = (): void => {
      onSelectConversation(conv);
    };

    return (
      <div
        key={conv.id}
        role="button"
        tabIndex={0}
        className={`task-item ${active ? 'is-current' : ''}`}
        onClick={handleSelect}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleSelect();
          }
        }}
        aria-current={active ? 'true' : undefined}
        aria-label={title}
      >
        <div className="task-item-body">
          <strong>{title}</strong>
          <span>
            {updated.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}
          </span>
        </div>
        <div className="task-actions">
          <button
            aria-label={`删除对话 ${title}`}
            className="delete-btn"
            onClick={(event) => {
              event.stopPropagation();
              onDeleteConversation(conv.id);
            }}
            type="button"
          >
            ×
          </button>
        </div>
      </div>
    );
  };

  return (
    <aside className="sidebar">
      {/* 整列可拖(Tauri 2) */}
      <div className="sidebar-drag" data-tauri-drag-region />

      <div className="sidebar-task-list" aria-label="对话列表">
        {sortedConversations.length === 0 ? (
          <div className="empty-tasks">
            <strong>还没有对话</strong>
            <span>从右侧输入框开始,把事情交给 Nexus。</span>
            <button type="button" className="empty-tasks-cta" onClick={onNewTask}>
              + 开始新对话
            </button>
          </div>
        ) : (
          sortedConversations.map(renderTask)
        )}
      </div>

      <div className="sidebar-footer-version">
        <span>Nexus v1.3.0</span>
      </div>
    </aside>
  );
}
