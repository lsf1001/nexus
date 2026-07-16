import { useState } from 'react';
import { useContextMenuTrigger, openContextMenuAt } from '../../lib/useContextMenuTrigger';
import type { Conversation } from '../../types';
import type { DesktopView } from './DesktopShell';

export interface SidebarProps {
  onViewChange: (view: DesktopView) => void;
  conversations: Conversation[];
  currentConversationId: string | null;
  wechatConnected: boolean;
  wechatInboxCount: number;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
}

/**
 * 左侧栏 — 扁平、符合直觉:
 *   顶部: 品牌 + 设置入口(常驻,不藏底部)
 *   主操作: + 新任务
 *   中部: 会话列表(扁平,微信任务用 channel-tag 标记)
 *   底部: 微信通道一行
 *
 * 设计原则:
 *   - 不显示未实现功能的占位(移除"今天"/"已完成"soon 占位)
 *   - 不重复显示分组(主/微信会话共用一个列表,channel-tag 区分)
 *   - 不嵌套 nav(只有主操作 + 列表,不需要 nav-item 路由层)
 */
export function Sidebar({
  onViewChange,
  conversations,
  currentConversationId,
  wechatConnected,
  wechatInboxCount,
  onSelectConversation,
  onDeleteConversation,
  onNewTask,
}: SidebarProps) {
  // 第九轮(2026-07-16):会话搜索 — 顶栏下方 input[type=search],
  // 按 title 子串过滤;空查询 = 全列表;无命中 = 显示"无匹配"提示
  // (empty-tasks 只在 conversations 本就空时出现)。
  const [searchQuery, setSearchQuery] = useState('');

  // 按更新时间倒序,新的在前 — 人类直觉就是"刚聊的放最上面"
  const sortedConversations = [...conversations].sort((a, b) => {
    const ta = new Date(a.updatedAt || a.createdAt).getTime();
    const tb = new Date(b.updatedAt || b.createdAt).getTime();
    return tb - ta;
  });

  const trimmedQuery = searchQuery.trim();
  const filteredConversations = trimmedQuery
    ? sortedConversations.filter((c) => (c.title || '新对话').includes(trimmedQuery))
    : sortedConversations;

  // 各交互元素右击复制(可访问性增强)
  const copyBrand = useContextMenuTrigger(() => 'Nexus · 个人 AI 助手', { label: '应用信息' });
  const copyNewTask = useContextMenuTrigger(() => '新建一个对话', { label: '操作' });
  const copyEmptyTasks = useContextMenuTrigger(
    () => '还没有对话 · 从右侧输入框开始,把事情交给 Nexus。',
    { label: '提示' }
  );
  const copyWechatLink = useContextMenuTrigger(
    () =>
      `微信通道 · ${wechatConnected ? '已连接' : '未绑定'}${wechatInboxCount > 0 ? ` · ${wechatInboxCount} 条未读` : ''}`,
    { label: '状态' }
  );
  const copySettingsLink = useContextMenuTrigger(
    () => '设置 · 打开设置页',
    { label: '入口' }
  );

  // 单个会话条目渲染 — 主 / 微信共用,通过 channel-tag 区分
  const renderTask = (conv: Conversation) => {
    const active = conv.id === currentConversationId;
    const isWechat = conv.channel === 'wechat';
    const updated = new Date(conv.updatedAt || conv.createdAt);
    const title = conv.title || '新对话';

    const onCopy = (e: React.MouseEvent): void => {
      const text = `${title}\n${updated.toLocaleString('zh-CN')}${isWechat ? ' · 微信' : ''}${active ? ' · 当前' : ''}`;
      openContextMenuAt(e, text, '任务');
    };

    return (
      <div
        key={conv.id}
        role="button"
        tabIndex={0}
        className={`task-item ${active ? 'is-current' : ''}`}
        onClick={() => onSelectConversation(conv)}
        onContextMenu={onCopy}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onSelectConversation(conv);
          }
        }}
        aria-current={active ? 'true' : undefined}
        aria-label={`${title}${isWechat ? ' · 微信' : ''}`}
      >
        <div className="task-item-body">
          <strong>{title}</strong>
          <span>
            {isWechat && <span className="channel-tag-inline">微信</span>}
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
            onContextMenu={(e) => e.stopPropagation()}
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
      {/* 整列拖拽(Tauri 2 属性标记);
       * sidebar 顶部 38px 与 macOS traffic lights 同高,整列可拖但
       * 内 button 等会自动 no-drag(tokens.css 全局规则)。 */}
      <div className="sidebar-brand" data-tauri-drag-region onContextMenu={copyBrand}>
        <div className="sidebar-brand-mark">N</div>
        <div className="sidebar-brand-text">
          <strong>Nexus</strong>
          <span>个人 AI 助手</span>
        </div>
        <button
          type="button"
          className="sidebar-settings-btn"
          aria-label="设置"
          title="设置"
          onClick={() => onViewChange('settings')}
          onContextMenu={copySettingsLink}
        >
          {/* 齿轮图标 — inline SVG,避免额外依赖 */}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>

      <button
        className="btn-new-task"
        onClick={onNewTask}
        onContextMenu={copyNewTask}
        aria-label="新建对话 (快捷键 Cmd+N / Ctrl+N)"
      >
        <span className="plus-mark" aria-hidden="true">+</span>
        <span>新对话</span>
      </button>

      <div className="sidebar-search">
        <input
          type="search"
          placeholder="搜索会话"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="搜索会话"
        />
      </div>

      <div className="sidebar-section" aria-label="对话列表">
        <div className="sidebar-section-title">
          <span>对话</span>
          {conversations.length > 0 && (
            <span className="conversation-count" aria-label={`共 ${conversations.length} 条`}>
              {conversations.length}
            </span>
          )}
        </div>
        <div className="recent-panel" aria-live="polite" aria-relevant="additions text">
          {sortedConversations.length === 0 ? (
            <div className="empty-tasks" onContextMenu={copyEmptyTasks}>
              <strong>还没有对话</strong>
              <span>从右侧输入框开始,把事情交给 Nexus。</span>
              <button type="button" className="empty-tasks-cta" onClick={onNewTask}>
                + 开始新对话
              </button>
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="sidebar-no-match" aria-live="polite">
              无匹配 “{trimmedQuery}”
            </div>
          ) : (
            filteredConversations.map(renderTask)
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <button
          className={`footer-link footer-link--wechat ${wechatConnected ? 'is-connected' : ''}`}
          type="button"
          onClick={() => onViewChange('wechat')}
          onContextMenu={copyWechatLink}
          aria-label={`微信通道 ${wechatConnected ? '已连接' : '未绑定'}`}
        >
          <span className="footer-link-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8.5 4C4.36 4 1 6.91 1 10.5c0 2.05 1.1 3.87 2.81 5.04L3 18l2.65-1.43c.91.25 1.88.4 2.85.4.21 0 .42-.01.63-.02-.13-.42-.21-.86-.21-1.32 0-.36.04-.71.11-1.05-.18.01-.35.02-.53.02-2.76 0-5-1.94-5-4.34S5.74 5.92 8.5 5.92s5 1.94 5 4.34c0 .22-.02.43-.05.64.4-.13.83-.22 1.27-.27.04-.31.06-.62.06-.94 0-.45-.04-.89-.11-1.31C13.81 5.43 11.36 4 8.5 4zm9.5 6c-3.59 0-6.5 2.46-6.5 5.5 0 1.67.86 3.16 2.21 4.16L13 22l1.95-1.1c.66.18 1.36.28 2.05.28 3.59 0 6.5-2.46 6.5-5.5S21.59 10 18 10zm-2.4 7.2-.9-1-2.1 1.05.95-1.95-.85-1 1.4-.05L14.5 12l.4 2.25 1.4.05-.85 1 .95 1.95-2.1-1.05z" />
            </svg>
          </span>
          <span className="footer-link-label">微信通道</span>
          <span className="footer-link-status">
            {wechatConnected ? '已连接' : '未绑定'}
            {wechatInboxCount > 0 && (
              <span className="wechat-inbox-badge" aria-label={`${wechatInboxCount} 条未读`}>
                {wechatInboxCount}
              </span>
            )}
          </span>
        </button>
      </div>
    </aside>
  );
}