/**
 * 消息列表(MessageList) + 加载 spinner。
 *
 * 拆出原因:ChatArea function body 内 message-list map + isLoading 渲染占 20 行,
 * 抽出后 ChatArea 顶部 JSX 更接近"布局壳"。后续 Plan 2 Phase 2 会在这里加
 * React.memo(每个 ChatBubble 已经计划走 memo + 优化 prop 传输)。
 *
 * 注意:Memo 隔离尚未引入(Phase 1 只拆文件,不动 React 渲染层);准备好
 * Phase 2 时改 ChatBubble → React.memo + custom equality 即可,不需改这里。
 */

import ChatBubble from '../ChatBubble';
import type { Message } from '../../types';

export interface MessageListProps {
  messages: ReadonlyArray<Message>;
  showThinking: boolean;
  isLoading: boolean;
  onCopy?: (content: string) => void;
}

export function MessageList({
  messages,
  showThinking,
  isLoading,
  onCopy,
}: MessageListProps) {
  return (
    <div className="message-list">
      {messages.map((msg) => (
        <ChatBubble
          key={msg.id}
          message={msg}
          showThinking={showThinking}
          onCopy={onCopy}
        />
      ))}
      {isLoading && (
        <div className="message-row is-assistant">
          <div className="loading-bubble" aria-label="助手正在输入">
            <span className="loading-dot" />
            <span className="loading-dot" />
            <span className="loading-dot" />
          </div>
        </div>
      )}
    </div>
  );
}
