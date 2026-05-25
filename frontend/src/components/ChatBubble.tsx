import type { Message } from '../types';

interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
}

function ChatBubble({ message, showThinking = true }: ChatBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-xl px-4 py-3 ${
          isUser ? 'bubble-user' : 'bubble-assistant'
        }`}
      >
        {message.content}
        {showThinking && message.thinking && (
          <div className="thinking-block">
            <div className="text-[10px] uppercase text-[var(--color-moss)] mb-2 flex items-center gap-1">
              🌿 思考过程
            </div>
            <pre className="whitespace-pre-wrap text-xs">{message.thinking}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatBubble;
