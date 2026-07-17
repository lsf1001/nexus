import { ChatView } from './ChatView';
import { ContextMenuHost } from './ContextMenuHost';
import { SetupView } from './SetupView';
import { Sidebar } from './Sidebar';
import { ToastHost } from '../ToastHost';
import type { Conversation } from '../../types';
import type { DesktopShellContext, DesktopView } from './DesktopShell';

export interface ShellLayoutProps {
  view: DesktopView;
  onViewChange: (view: DesktopView) => void;
  conversations: Conversation[];
  currentConversationId: string | null;
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
  onSelectConversation,
  onDeleteConversation,
  onNewTask,
  context,
  onConnectedChange,
  onSessionCreated,
  resetCounter,
}: ShellLayoutProps) {
  return (
    <div className="nexus-desktop">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={onSelectConversation}
        onDeleteConversation={onDeleteConversation}
        onNewTask={onNewTask}
        onOpenPreferences={() => onViewChange('chat')}
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

      <ContextMenuHost />
      <ToastHost />
    </div>
  );
}
