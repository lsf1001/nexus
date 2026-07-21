/**
 * 消息列表(MessageList) + 加载 spinner。
 *
 * 拆出原因:ChatArea function body 内 message-list map + isLoading 渲染占 20 行,
 * 抽出后 ChatArea 顶部 JSX 更接近“布局壳”。
 *
 * React.memo + 自定义比较器:见 ./messageListProps.ts。2026-07-20 修产品 bug —
 * 流式期间最后一条 content 增量的更新需要 MessageList 比较器按值比较 content /
 * thinking / toolCalls,不再把责任完全下放给 ChatBubble 自身的 memo。
 */

import { memo } from 'react';
import ChatBubble from '../ChatBubble';
import {
  messageListPropsAreEqual,
  type MessageListProps,
} from './messageListProps';

export type { MessageListProps };

function MessageListInner({
  messages,
  showThinking,
  isLoading,
  onCopy,
  onRetry,
}: MessageListProps) {
  return (
    <div className="message-list">
      {messages.map((msg) => (
        <ChatBubble
          key={msg.id}
          message={msg}
          showThinking={showThinking}
          onCopy={onCopy}
          onRetry={onRetry}
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

export const MessageList = memo(MessageListInner, messageListPropsAreEqual);