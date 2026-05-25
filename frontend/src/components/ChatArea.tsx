import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import { ChatBubble } from './ChatBubble';
import type { StreamEvent, WSMessage, Message } from '../types';

function ChatArea() {
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const [displayMessages, setDisplayMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [showThinking, setShowThinking] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const setWsError = useStore((s) => s.setWsError);

  const wsUrl = import.meta.env.DEV
    ? 'ws://localhost:8000/api/ws'
    : 'ws://localhost:8000/api/ws';

  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onerror = () => {
      setWsConnected(false);
      setWsError('连接错误');
    };

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onclose = () => {
      setWsConnected(false);
    };

    ws.onmessage = (event) => {
      const data: StreamEvent = JSON.parse(event.data);

      switch (data.type) {
        case 'thinking': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            messagesRef.current[lastIdx].thinking = (messagesRef.current[lastIdx].thinking || '') + data.content;
            setDisplayMessages([...messagesRef.current]);
          }
          break;
        }
        case 'chunk': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            if (messagesRef.current[lastIdx].role === 'assistant') {
              messagesRef.current[lastIdx].content += data.content;
            }
            setDisplayMessages([...messagesRef.current]);
          }
          break;
        }
        case 'final': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            messagesRef.current[lastIdx].content = data.content;
            setDisplayMessages([...messagesRef.current]);
          }
          setIsLoading(false);
          break;
        }
        case 'done': {
          setIsLoading(false);
          break;
        }
        case 'error': {
          setWsError(data.content);
          setIsLoading(false);
          break;
        }
        case 'token_usage': {
          break;
        }
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayMessages, isLoading]);

  const handleSend = () => {
    const messageContent = input.trim();
    if (!messageContent || !wsConnected) return;

    setIsLoading(true);
    setInput('');

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: messageContent,
    };
    messagesRef.current.push(userMsg);
    setDisplayMessages([...messagesRef.current]);

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
    };
    messagesRef.current.push(assistantMsg);
    setDisplayMessages([...messagesRef.current]);

    const msg: WSMessage = { content: messageContent };
    wsRef.current?.send(JSON.stringify(msg));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-white">
      <div className="border-b border-gray-200 px-4 py-2 flex items-center justify-between">
        <span className="text-sm text-gray-600">MiniMax-M2.7</span>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={showThinking}
            onChange={(e) => setShowThinking(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300"
          />
          显示思考
        </label>
      </div>

      {!wsConnected && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-sm text-red-600">
          连接已断开，请刷新页面重新连接
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4">
        {displayMessages.length === 0 && !isLoading ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p className="text-lg">Nexus 智能助手</p>
              <p className="text-sm mt-2">输入消息开始对话</p>
            </div>
          </div>
        ) : (
          displayMessages.map((msg) => (
            <ChatBubble key={msg.id} message={msg} showThinking={showThinking} />
          ))
        )}
        {isLoading && (
          <div className="flex justify-start mb-4">
            <div className="bg-gray-100 px-4 py-3 rounded-lg">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
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
            disabled={!wsConnected || isLoading}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
          <button
            onClick={handleSend}
            disabled={!wsConnected || !input.trim() || isLoading}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatArea;