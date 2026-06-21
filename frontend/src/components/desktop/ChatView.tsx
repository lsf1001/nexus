import ChatArea from '../ChatArea';
import type { DesktopShellContext } from './DesktopShell';

interface ChatViewProps {
  context: DesktopShellContext;
  onConnectedChange: (connected: boolean) => void;
  onSessionCreated: (sessionId: string, title: string) => void;
  resetCounter: number;
}

type ConnectionState = 'connecting' | 'online' | 'offline';

function resolveConnectionState(wsConnected: boolean, modelConfigured: boolean): ConnectionState {
  if (wsConnected) return 'online';
  if (modelConfigured) return 'connecting';
  return 'offline';
}

function PillLabel({ state }: { state: ConnectionState }) {
  if (state === 'online') return <>本地在线</>;
  if (state === 'connecting') return <>正在连接本地助手</>;
  return <>本地助手离线</>;
}

export function ChatView({
  context,
  onConnectedChange,
  onSessionCreated,
  resetCounter,
}: ChatViewProps) {
  const currentConv = context.conversations.find(
    (conv) => conv.id === context.currentConversationId,
  ) ?? null;

  const connectionState = resolveConnectionState(
    context.wsConnected,
    Boolean(context.modelName),
  );
  const pillClass = `status-pill ${connectionState === 'online' ? '' : `is-${connectionState}`}`;

  return (
    <>
      <header className="topbar">
        <div className="topbar-topic">
          <strong>{currentConv?.title || '新任务'}</strong>
          <span>
            {context.modelName || '未配置模型'}
            {currentConv ? ` · ${currentConv.channel === 'wechat' ? '微信通道' : '本地对话'}` : ''}
          </span>
        </div>
        <div className="topbar-actions">
          <span className={pillClass} role="status" aria-live="polite">
            <span className="dot" />
            <PillLabel state={connectionState} />
          </span>
        </div>
      </header>

      <ChatArea
        resetTrigger={resetCounter}
        conversationId={context.currentConversationId}
        onConnectedChange={onConnectedChange}
        onSessionCreated={onSessionCreated}
        connectionState={connectionState}
        activeConversationTitle={currentConv?.title ?? null}
        conversationCount={context.conversations.length}
      />
    </>
  );
}
