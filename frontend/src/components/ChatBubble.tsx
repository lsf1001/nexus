import ReactMarkdown from 'react-markdown';
import type { Message } from '../types';

interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
  onCopy?: (content: string) => void;
}

function ChatBubble({ message, showThinking = true, onCopy }: ChatBubbleProps) {
  const isUser = message.role === 'user';

  const handleCopy = () => {
    const text = message.content || message.thinking || '';
    onCopy?.(text);
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] px-4 py-3 ${
          isUser
            ? 'bg-[#4a7c59] text-white rounded-2xl rounded-br-sm'
            : 'bg-[#1a1a1a] border border-[#2a2a2a] text-gray-200 rounded-2xl rounded-bl-sm'
        }`}
      >
        {!isUser && onCopy && (
          <button
            onClick={handleCopy}
            className="float-right ml-2 p-1 rounded hover:bg-[#2a2a2a] text-gray-500 hover:text-gray-300 transition-colors"
            title="复制内容"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </button>
        )}
        {showThinking && message.thinking && (
          <div className="mb-3 p-3 bg-[#252525] rounded-xl border-l-2 border-[#4a7c59]">
            <div className="text-xs text-[#4a7c59] font-medium mb-2 flex items-center gap-1">
              <span>🌿</span> 思考过程
            </div>
            <pre className="text-xs text-gray-400 whitespace-pre-wrap font-mono">{message.thinking}</pre>
          </div>
        )}
        <div className={`prose prose-sm max-w-none ${isUser ? 'text-white' : 'text-gray-200'} prose-p:my-1`}>
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

export default ChatBubble;