import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import ChatBubble from './ChatBubble';
import type { StreamEvent, WSMessage, Message } from '../types';

function ChatArea() {
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const [displayMessages, setDisplayMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const showThinking = useStore((s) => s.showThinking);
  const modelName = useStore((s) => s.modelName);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const setWsError = useStore((s) => s.setWsError);
  const setModelName = useStore((s) => s.setModelName);

  const wsUrl = 'ws://localhost:8000/api/ws';
  const apiUrl = 'http://localhost:8000/api';

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
            messagesRef.current[lastIdx].thinking =
              (messagesRef.current[lastIdx].thinking || '') + data.content;
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

  // 获取模型信息
  useEffect(() => {
    fetch(`${apiUrl}/model`)
      .then(res => res.json())
      .then(data => {
        if (data.model_name) {
          setModelName(data.model_name);
        }
      })
      .catch(console.error);
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
    <div className="flex-1 flex flex-col bg-[var(--color-cream)]">
      {/* Header */}
      <div className="h-[50px] border-b border-[var(--color-border)] px-5 flex items-center justify-between">
        <span className="text-sm text-[var(--color-text-muted)]">{modelName}</span>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-[var(--color-moss)]' : 'bg-gray-400'}`} />
          <span className={`text-xs ${wsConnected ? 'text-[var(--color-moss)]' : 'text-gray-500'}`}>
            {wsConnected ? '已连接' : '未连接'}
          </span>
        </div>
      </div>

      {/* 连接断开提示 */}
      {!wsConnected && (
        <div className="bg-gray-100 border-b border-gray-200 px-4 py-2 text-sm text-gray-600">
          连接已断开，请刷新页面重新连接
        </div>
      )}

      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto p-5">
        {displayMessages.length === 0 && !isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-[var(--color-text-muted)]">
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
            <div className="bg-[var(--color-cream-dark)] px-4 py-3 rounded-lg">
              <div className="flex gap-1">
                <span
                  className="w-2 h-2 bg-[var(--color-moss)] rounded-full animate-bounce"
                  style={{ animationDelay: '0ms' }}
                />
                <span
                  className="w-2 h-2 bg-[var(--color-moss)] rounded-full animate-bounce"
                  style={{ animationDelay: '150ms' }}
                />
                <span
                  className="w-2 h-2 bg-[var(--color-moss)] rounded-full animate-bounce"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={wsConnected ? '输入消息...' : '连接中...'}
            disabled={!wsConnected || isLoading}
            className="flex-1 px-4 py-3 border border-[var(--color-border)] rounded-3xl bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-moss)] disabled:bg-gray-100"
          />
          <button
            onClick={handleSend}
            disabled={!wsConnected || !input.trim() || isLoading}
            className="w-11 h-11 bg-[var(--color-moss)] text-white rounded-full hover:bg-[var(--color-forest-start)] disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-lg"
          >
            ➤
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatArea;