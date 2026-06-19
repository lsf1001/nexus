import { ChatView } from './ChatView';
import { ContextMenuHost } from './ContextMenuHost';
import { SettingsView } from './SettingsView';
import { SetupView } from './SetupView';
import { Sidebar } from './Sidebar';
import { SketchLine } from './SketchLines';
import { WechatAssistantView } from './WechatAssistantView';
import { useStore } from '../../store/useStore';
import type { Conversation } from '../../types';
import type { DesktopShellContext, DesktopView } from './DesktopShell';

export interface ShellLayoutProps {
  view: DesktopView;
  onViewChange: (view: DesktopView) => void;
  conversations: Conversation[];
  currentConversationId: string | null;
  wechatConnected: boolean;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
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
  context,
  onConnectedChange,
  onSessionCreated,
  resetCounter,
}: ShellLayoutProps) {
  const wechatInboxCount = useStore((state) => state.wechatInbox.length);

  return (
    <div className="nexus-desktop">
      <div className="window">
        <Sidebar
          onViewChange={onViewChange}
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
          {view === 'wechat' && <WechatAssistantView onBack={() => onViewChange('chat')} />}
          {view === 'settings' && <SettingsView onBack={() => onViewChange('chat')} />}
        </main>

        {/* 手绘装饰:呼应原型的"暖色个人助理"风格 */}
        <SketchLine position="top-right" />
        <SketchLine position="bottom-left" />
      </div>

      {/* 全局右键菜单浮层(挂在最外层,避免被父级 overflow 切掉) */}
      <ContextMenuHost />
    </div>
  );
}
