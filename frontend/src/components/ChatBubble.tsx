import ReactMarkdown from 'react-markdown';
import type { Message } from '../types';

interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
}

function ChatBubble({ message, showThinking = true }: ChatBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] px-5 py-3 ${
          isUser
            ? 'bg-gradient-to-br from-[#2d4a3a] to-[#4a7c59] text-white rounded-2xl rounded-br-sm'
            : 'bg-white border border-[#e0dcd4] rounded-2xl rounded-bl-sm shadow-sm'
        }`}
      >
        {showThinking && message.thinking && (
          <div className="mb-3 p-3 bg-[#4a7c59]/10 rounded-xl border-l-2 border-[#4a7c59]">
            <div className="text-xs text-[#4a7c59] font-medium mb-1 flex items-center gap-1">
              <span>🌿</span> 思考过程
            </div>
            <pre className="text-xs text-[#6b7c6b] whitespace-pre-wrap">{message.thinking}</pre>
          </div>
        )}
        <div className={`prose prose-sm max-w-none ${isUser ? 'text-white' : 'text-[#2d4a3a]'} prose-p:my-1`}>
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

export default ChatBubble;
