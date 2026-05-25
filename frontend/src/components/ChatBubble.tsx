import type { Message } from '../types';

interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
}

function ChatBubble({ message, showThinking = true }: ChatBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-xl ${isUser ? 'bg-blue-500 text-white' : 'bg-gray-100'} px-4 py-3 rounded-lg`}>
        {message.content}
        {showThinking && message.thinking && (
          <div className="mt-2 text-sm text-gray-500 border-t pt-2">
            <details>
              <summary className="cursor-pointer">思考过程</summary>
              <pre className="whitespace-pre-wrap text-xs mt-1">{message.thinking}</pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatBubble;
