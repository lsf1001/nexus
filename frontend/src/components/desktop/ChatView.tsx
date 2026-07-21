import { useMemo } from 'react';
import ChatArea from '../ChatArea';
import { StatusBar } from './StatusBar';
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
  return 'offline' as ConnectionState;
}

export function ChatView({
  context,
  onConnectedChange,
  onSessionCreated,
  resetCounter,
}: ChatViewProps) {
  const currentConv = useMemo(
    () => context.conversations.find(
      (conv) => conv.id === context.currentConversationId,
    ) ?? null,
    [context.conversations, context.currentConversationId],
  );

  const connectionState = resolveConnectionState(
    context.wsConnected,
    Boolean(context.modelName),
  );

  return (
    <>
      {/* V3 (2026-07-20) WorkBuddy 极简 IDE 风格:
       *  - 22px 顶栏(从 36 收):仅左侧当前标题(⌘K 按钮已删,快捷键 Cmd/Ctrl+K 仍全局生效)
       *  - 14px 底栏(新增 StatusBar):模型 + 连接点 + spacer + local
       *  - 主对话区 ChatArea 限宽 720px 居中(从 760 收)
       *  - 整条顶栏 drag-region 让 macOS chrome 整窗可拖 */}
      <div className="chat-area-wrap">
        <header className="chat-status-bar" data-tauri-drag-region>
          <span className="chat-status-topic" title={currentConv?.title || '新任务'}>
            {currentConv?.title || '新任务'}
            {currentConv?.channel === 'wechat' && <span className="chat-status-channel">· 微信通道</span>}
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

        <StatusBar
          wsConnected={context.wsConnected}
          modelConfigured={Boolean(context.modelName)}
        />
      </div>
    </>
  );
}
