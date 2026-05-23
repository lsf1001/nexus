import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import { ChatBubble } from './ChatBubble';

interface ChatAreaProps {
  onSend: (content: string) => void;
}

export function ChatArea({ onSend }: ChatAreaProps) {
  const { currentSessionId, messages, wsConnected } = useStore();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const currentMessages = currentSessionId ? messages[currentSessionId] || [] : [];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentMessages]);

  const handleSend = () => {
    if (input.trim() && wsConnected) {
      onSend(input.trim());
      setInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-white">
      <div className="flex-1 overflow-y-auto p-4">
        {currentMessages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p className="text-lg">Nexus 智能助手</p>
              <p className="text-sm mt-2">输入消息开始对话</p>
            </div>
          </div>
        ) : (
          currentMessages.map((msg) => <ChatBubble key={msg.id} message={msg} />)
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-gray-200 p-4">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={wsConnected ? '输入消息...' : '连接中...'}
            disabled={!wsConnected}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
          <button
            onClick={handleSend}
            disabled={!wsConnected || !input.trim()}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}