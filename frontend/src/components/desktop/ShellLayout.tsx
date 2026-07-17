import { ChatView } from './ChatView';
import { ContextMenuHost } from './ContextMenuHost';
import { SetupView } from './SetupView';
import { Sidebar } from './Sidebar';
import { ToastHost } from '../ToastHost';
import { useStore } from '../../store';
import type { Conversation } from '../../types';
import type { DesktopShellContext, DesktopView } from './DesktopShell';
import type { PreferencesTab } from './PreferencesDrawer';

export interface ShellLayoutProps {
  view: DesktopView;
  onViewChange: (view: DesktopView) => void;
  conversations: Conversation[];
  currentConversationId: string | null;
  wechatConnected: boolean;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
  /**
   * 第十三轮(2026-07-17):打开偏好抽屉。
   * 不传 tab → 通用(齿轮入口);传 'wechat' → 落点在微信通道(底栏入口)。
   */
  onOpenPreferences: (tab?: PreferencesTab) => void;
  context: DesktopShellContext;
  onConnectedChange: (connected: boolean) => void;
  onSessionCreated: (sessionId: string, title: string) => void;
  resetCounter: number;
}

export function ShellLayout({
  view,
  onViewChange,
  conversations,
  currentConversationId,
  wechatConnected,
  onSelectConversation,
  onDeleteConversation,
  onNewTask,
  onOpenPreferences,
  context,
  onConnectedChange,
  onSessionCreated,
  resetCounter,
}: ShellLayoutProps) {
  const wechatInboxCount = useStore((state) => state.channelInbox['wechat']?.length ?? 0);

  return (
    <div className="nexus-desktop">
      {/* 整窗直接铺,不再有 .window 卡片嵌套。
       * 顶部 38px 让给 macOS traffic lights (titleBarStyle=Overlay + hiddenTitle)。
       * 拖拽区由 CSS .drag-region + data-tauri-drag-region 标记,
       * sidebar 透到 traffic light 下方而不挡点。 */}
      <Sidebar
        onViewChange={onViewChange}
        onOpenPreferences={onOpenPreferences}
        conversations={conversations}
        currentConversationId={currentConversationId}
        wechatConnected={wechatConnected}
        wechatInboxCount={wechatInboxCount}
        onSelectConversation={onSelectConversation}
        onDeleteConversation={onDeleteConversation}
        onNewTask={onNewTask}
      />

      <main className="main">
        {view === 'setup' && <SetupView onDone={() => onViewChange('chat')} />}
        {view === 'chat' && (
          <ChatView
            context={context}
            onConnectedChange={onConnectedChange}
            onSessionCreated={onSessionCreated}
            resetCounter={resetCounter}
          />
        )}
      </main>

      {/* 全局右键菜单浮层(挂在最外层,避免被父级 overflow 切掉) */}
      <ContextMenuHost />
      {/* 全局 toast 浮层 — 替代散落 console.warn,提示用户"复制失败"等非阻塞问题 */}
      <ToastHost />
    </div>
  );
}