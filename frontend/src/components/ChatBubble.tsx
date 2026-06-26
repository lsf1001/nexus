import ReactMarkdown from 'react-markdown';
import type { Message } from '../types';
import { useContextMenuTrigger } from '../lib/useContextMenuTrigger';

interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
  onCopy?: (content: string) => void;
}

/** 友好时间格式:今天 HH:MM / 昨天 HH:MM / YYYY-MM-DD HH:MM */
function formatTimestamp(d: Date): string {
  const now = new Date();
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, '0');
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (sameDay(d, now)) return `今天 ${hm}`;
  if (sameDay(d, yesterday)) return `昨天 ${hm}`;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`;
}

function ChatBubble({ message, showThinking = true, onCopy }: ChatBubbleProps) {
  const isUser = message.role === 'user';
  const roleClass = isUser ? 'is-user' : 'is-assistant';

  const handleCopy = () => {
    const text = message.content || message.thinking || '';
    onCopy?.(text);
  };

  const timestamp = message.createdAt ? formatTimestamp(message.createdAt) : '';

  // 右击消息任意位置 → 弹"复制 消息"菜单（user / assistant 都支持）
  const handleContextMenu = useContextMenuTrigger(
    () => {
      const parts: string[] = [];
      if (message.thinking) parts.push(`[思考] ${message.thinking}`);
      if (message.content) parts.push(message.content);
      return parts.join('\n\n');
    },
    { label: isUser ? '消息' : '回复' }
  );

  return (
    <div className={`message-row ${roleClass}`}>
      <div
        className={`message-bubble ${isUser ? 'message-user' : 'message-assistant'}`}
        onContextMenu={handleContextMenu}
      >
        {!isUser && onCopy && (
          <button
            onClick={handleCopy}
            className="copy-button"
            type="button"
            title="复制内容"
            aria-label="复制消息"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
          </button>
        )}
        {showThinking && message.thinking && (
          <div className="thinking-card">
            <div className="thinking-title">
              <span aria-hidden="true">🌿</span> 思考过程
            </div>
            <pre className="thinking-content">{message.thinking}</pre>
          </div>
        )}
        <div className={`message-markdown ${isUser ? 'user' : 'assistant'}`}>
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>
      </div>
      {timestamp && <div className={`message-timestamp ${roleClass}`}>{timestamp}</div>}
    </div>
  );
}

export default ChatBubble;
