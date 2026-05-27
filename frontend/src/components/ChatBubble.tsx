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
        className={`max-w-[80%] px-5 py-4 ${
          isUser
            ? 'bg-gradient-to-br from-[#4a7c59] to-[#2d4a3a] text-white rounded-2xl rounded-br-sm shadow-lg'
            : 'bg-white/90 backdrop-blur border border-white/30 text-[#2c3e2d] rounded-2xl rounded-bl-sm shadow-lg'
        }`}
      >
        {showThinking && message.thinking && (
          <div className="mb-4 p-4 bg-white/50 backdrop-blur rounded-xl border-l-3 border-[#8fbc8f]">
            <div className="text-xs text-[#4a7c59] font-medium mb-2 flex items-center gap-1">
              <span>🌿</span> 思考过程
            </div>
            <pre className="text-xs text-[#4a5d42] whitespace-pre-wrap">{message.thinking}</pre>
          </div>
        )}
        <div className={`prose prose-sm max-w-none ${isUser ? 'text-white' : 'text-[#2c3e2d]'} prose-p:my-1`}>
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

export default ChatBubble;
