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
      {/* 第六轮(2026-07-15):删 66px 顶栏。Claude Desktop 不在主区顶部加任何条。
       * 当前会话标题由 sidebar 的 is-current task-item 标记;
       * 模型名 + 状态 pill 改为 chat-area 顶部右侧的 36px 高细条,
       * 不占主区横向空间,只占角落一行。 */}
      <div className="chat-area-wrap">
        <header className="chat-status-bar" data-tauri-drag-region>
          <span className="chat-status-topic" title={currentConv?.title || '新任务'}>
            {currentConv?.title || '新任务'}
            {currentConv?.channel === 'wechat' && <span className="chat-status-channel">· 微信通道</span>}
          </span>
          <span className={pillClass} role="status" aria-live="polite">
            <span className="dot" />
            <PillLabel state={connectionState} />
          </span>
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
      </div>
    </>
  );
}
