import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { Conversation } from '../../types';

export interface SidebarProps {
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
}

/**
 * 左侧栏 — Claude 风格左 rail（Task 2.2 重建）。
 *   - 顶部:品牌块 `.sidebar-brand`(logo + Nexus)
 *   - 新对话按钮 `.btn-new-task`(导航 /chat 由 DesktopShell 的 onNewTask 处理)
 *   - 搜索 input[type="search"](本地实时过滤 Recents)
 *   - Recents 列表 `.recent-panel`(扁平等宽 task-item + 当前态左竖条,沿用 e2e 选择器)
 *   - Starred:store 暂无 starred 字段,无星标会话时隐藏(不 over-build)
 *   - 底部 `.sidebar-footer`:账户下拉 + 版本号
 * 保留 `.sidebar` 根类与 `.task-item` / `data-testid` 等 e2e 选择器契约。
 */
export function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onDeleteConversation,
  onNewTask,
}: SidebarProps) {
  const [query, setQuery] = useState('');

  const sortedConversations = [...conversations].sort((a, b) => {
    const ta = new Date(a.updatedAt || a.createdAt).getTime();
    const tb = new Date(b.updatedAt || b.createdAt).getTime();
    return tb - ta;
  });

  const q = query.trim();
  const filteredConversations = q
    ? sortedConversations.filter((conv) =>
        (conv.title || '新对话').includes(q),
      )
    : sortedConversations;

  // Starred 占位:store 暂无 starred 字段,无星标会话时不渲染该区(隐藏)。
  const starredConversations = conversations.filter(
    (conv) => (conv as Conversation & { starred?: boolean }).starred === true,
  );

  const renderTask = (conv: Conversation) => {
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
      {/* 整列可拖(Tauri 2):顶部 38px 让位 macOS traffic lights */}
      <div className="sidebar-drag" data-tauri-drag-region />

      <div className="sidebar-brand">
        <div className="sidebar-brand-mark">N</div>
        <span className="sidebar-brand-name">Nexus</span>
      </div>

      <div className="sidebar-section">
        <Button
          className="btn-new-task"
          aria-label="新建对话 (快捷键 Cmd+N / Ctrl+N)"
          type="button"
          variant="outline"
          onClick={onNewTask}
        >
          <span className="plus-mark" aria-hidden="true">+</span>
          新建对话
        </Button>

        <input
          type="search"
          className="sidebar-search"
          placeholder="搜索对话"
          aria-label="搜索对话"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="sidebar-section-title">Recents</div>

        <div className="recent-panel" aria-live="polite" aria-relevant="additions text">
          {conversations.length === 0 ? (
            <div className="empty-tasks">
              <strong>还没有对话</strong>
              <span>从右侧输入框开始,把事情交给 Nexus。</span>
              <button type="button" className="empty-tasks-cta" onClick={onNewTask}>
                + 开始新对话
              </button>
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="no-match">无匹配对话</div>
          ) : (
            filteredConversations.map(renderTask)
          )}
        </div>

        {starredConversations.length > 0 && (
          <div className="sidebar-starred">
            <div className="sidebar-section-title">Starred</div>
            {starredConversations.map(renderTask)}
          </div>
        )}
      </div>

      <div className="sidebar-footer">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              className="account-trigger"
              aria-label="账户菜单"
              type="button"
              variant="ghost"
              size="icon"
            >
              N
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="top">
            <DropdownMenuItem>设置</DropdownMenuItem>
            <DropdownMenuItem>退出登录</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <span className="sidebar-version">Nexus v1.3.0</span>
      </div>
    </aside>
  );
}
