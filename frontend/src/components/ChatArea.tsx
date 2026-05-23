import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import { ChatBubble } from './ChatBubble';
import type { StreamEvent, WSMessage } from '../types';

function ChatArea() {
  const wsRef = useRef<WebSocket | null>(null);
  const thinkingBufferRef = useRef<string>('');
  const currentMessageIdRef = useRef<string | null>(null);

  const [input, setInput] = useState('');
  const [showThinkingLocal, setShowThinkingLocal] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const currentSessionId = useStore((s) => s.currentSessionId);
  const messages = useStore((s) => s.messages);
  const wsConnected = useStore((s) => s.wsConnected);
  const isLoading = useStore((s) => s.isLoading);
  const contextUsage = useStore((s) => s.contextUsage);

  const currentMessages = currentSessionId ? messages[currentSessionId] || [] : [];

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    wsRef.current = ws;

    ws.onopen = () => useStore.getState().setWsConnected(true);
    ws.onclose = () => useStore.getState().setWsConnected(false);
    ws.onerror = () => {
      useStore.getState().setWsConnected(false);
      useStore.getState().setWsError('连接错误');
    };

    ws.onmessage = (event) => {
      const data: StreamEvent = JSON.parse(event.data);

      switch (data.type) {
        case 'session_created': {
          const newSession = {
            id: data.session_id,
            title: '新对话',
            showThinking: true,
            createdAt: new Date(),
            updatedAt: new Date(),
          };
          useStore.getState().addSession(newSession);
          useStore.getState().setCurrentSession(data.session_id);
          break;
        }
        case 'thinking': {
          const sid = useStore.getState().currentSessionId;
          if (sid) {
            thinkingBufferRef.current += data.content;
            const state = useStore.getState();
            const msgs = state.messages[sid] || [];
            const lastMsg = msgs[msgs.length - 1];

            if (lastMsg && !lastMsg.thinking) {
              useStore.getState().updateMessage(sid, lastMsg.id, { content: thinkingBufferRef.current });
            } else if (!lastMsg) {
              const msgId = crypto.randomUUID();
              currentMessageIdRef.current = msgId;
              useStore.getState().addMessage(sid, {
                id: msgId,
                role: 'assistant',
                content: data.content,
                createdAt: new Date(),
              });
            }
          }
          break;
        }
        case 'tool_result': {
          const sid = useStore.getState().currentSessionId;
          if (sid && currentMessageIdRef.current) {
            useStore.getState().updateMessage(sid, currentMessageIdRef.current, {
              content: thinkingBufferRef.current + '\n[工具返回] ' + data.content,
            });
          }
          break;
        }
        case 'final': {
          const sid = useStore.getState().currentSessionId;
          if (sid && currentMessageIdRef.current) {
            useStore.getState().updateMessage(sid, currentMessageIdRef.current, {
              content: data.content,
              thinking: thinkingBufferRef.current,
            });
            thinkingBufferRef.current = '';
            currentMessageIdRef.current = null;
          }
          useStore.getState().setIsLoading(false);
          break;
        }
        case 'done': {
          useStore.getState().setIsLoading(false);
          break;
        }
        case 'error': {
          useStore.getState().setWsError(data.content);
          useStore.getState().setIsLoading(false);
          break;
        }
      }
    };

    return () => ws.close();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentMessages, isLoading]);

  const handleSend = () => {
    const state = useStore.getState();
    if (input.trim() && state.wsConnected && !state.isLoading) {
      thinkingBufferRef.current = '';
      currentMessageIdRef.current = null;
      useStore.getState().setIsLoading(true);

      const msg: WSMessage = {
        session_id: state.currentSessionId || undefined,
        content: input.trim(),
      };
      wsRef.current?.send(JSON.stringify(msg));
      setInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleThinkingToggle = (checked: boolean) => {
    setShowThinkingLocal(checked);
    useStore.getState().setShowThinking(checked);
  };

  return (
    <div className="flex-1 flex flex-col bg-white">
      <div className="border-b border-gray-200 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">MiniMax-M2.7</span>
          <div className="text-xs text-gray-400">
            {contextUsage > 0 ? `${contextUsage}%` : '-'}
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={showThinkingLocal}
            onChange={(e) => handleThinkingToggle(e.target.checked)}
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
        {currentMessages.length === 0 && !isLoading ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p className="text-lg">Nexus 智能助手</p>
              <p className="text-sm mt-2">输入消息开始对话</p>
            </div>
          </div>
        ) : (
          <>
            {currentMessages.map((msg) => <ChatBubble key={msg.id} message={msg} />)}
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
          </>
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