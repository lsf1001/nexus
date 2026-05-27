import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import ChatBubble from './ChatBubble';
import totoroGif from '../assets/totoro.gif';
import type { StreamEvent, WSMessage, Message } from '../types';

interface ChatAreaProps {
  onConnectedChange?: (connected: boolean) => void;
}

function ChatArea({ onConnectedChange }: ChatAreaProps) {
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const [displayMessages, setDisplayMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const showThinking = useStore((s) => s.showThinking);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);

  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/api/ws?token=nexus-default-token`;

  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      onConnectedChange?.(true);
    };

    ws.onclose = () => {
      setWsConnected(false);
      onConnectedChange?.(false);
    };

    ws.onerror = () => {
      setWsConnected(false);
      onConnectedChange?.(false);
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
            messagesRef.current[lastIdx].content = data.content || '';
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
          setIsLoading(false);
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
      createdAt: new Date(),
    };
    messagesRef.current.push(userMsg);
    setDisplayMessages([...messagesRef.current]);

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
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

  const insertPrompt = (text: string) => {
    setInput(text);
    inputRef.current?.focus();
  };

  return (
    <div className="flex-1 flex flex-col bg-[#faf8f5]">
      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto">
        {displayMessages.length === 0 && !isLoading ? (
          /* 欢迎界面 */
          <div className="flex flex-col items-center justify-center h-full px-4">
            {/* 龙猫 */}
            <div className="mb-8">
              <img
                src={totoroGif}
                alt="龙猫"
                className="w-32 h-32 rounded-3xl object-cover shadow-lg"
              />
            </div>

            {/* 标题 */}
            <h2 className="text-2xl font-medium text-[#2d4a3a] mb-2">你好，我是 Nexus</h2>
            <p className="text-[#6b7c6b] mb-8">我可以帮你解答问题、编写代码、分析数据...</p>

            {/* 快捷提示 */}
            <div className="grid grid-cols-2 gap-3 w-full max-w-md">
              <button
                onClick={() => insertPrompt('帮我写一段 Python 代码')}
                className="p-4 rounded-2xl bg-white border border-[#e0dcd4] text-left hover:shadow-md hover:border-[#8fbc8f] transition-all"
              >
                <div className="text-sm font-medium mb-1 text-[#2d4a3a]">写代码</div>
                <div className="text-xs text-[#6b7c6b]">Python、JavaScript...</div>
              </button>
              <button
                onClick={() => insertPrompt('帮我分析这份数据')}
                className="p-4 rounded-2xl bg-white border border-[#e0dcd4] text-left hover:shadow-md hover:border-[#8fbc8f] transition-all"
              >
                <div className="text-sm font-medium mb-1 text-[#2d4a3a]">分析数据</div>
                <div className="text-xs text-[#6b7c6b]">Excel、CSV、JSON...</div>
              </button>
              <button
                onClick={() => insertPrompt('解释一下这个概念')}
                className="p-4 rounded-2xl bg-white border border-[#e0dcd4] text-left hover:shadow-md hover:border-[#8fbc8f] transition-all"
              >
                <div className="text-sm font-medium mb-1 text-[#2d4a3a]">知识问答</div>
                <div className="text-xs text-[#6b7c6b]">解释概念、回答问题...</div>
              </button>
              <button
                onClick={() => insertPrompt('帮我写一篇文章')}
                className="p-4 rounded-2xl bg-white border border-[#e0dcd4] text-left hover:shadow-md hover:border-[#8fbc8f] transition-all"
              >
                <div className="text-sm font-medium mb-1 text-[#2d4a3a]">写作助手</div>
                <div className="text-xs text-[#6b7c6b]">文章、邮件、报告...</div>
              </button>
            </div>
          </div>
        ) : (
          /* 对话消息 */
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
            {displayMessages.map((msg) => (
              <ChatBubble key={msg.id} message={msg} showThinking={showThinking} />
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-white px-4 py-3 rounded-2xl border border-[#e0dcd4]">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-[#4a7c59] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-[#4a7c59] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-[#4a7c59] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t border-[#e0dcd4] bg-white">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3 bg-[#faf8f5] rounded-2xl border border-[#e0dcd4] px-4 py-3 focus-within:border-[#4a7c59] focus-within:shadow-sm transition-all">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={wsConnected ? '输入消息...' : '连接中...'}
              disabled={!wsConnected || isLoading}
              rows={1}
              className="flex-1 bg-transparent resize-none focus:outline-none text-[#2d4a3a] placeholder-[#6b7c6b] disabled:text-[#999]"
            />
            <button
              onClick={handleSend}
              disabled={!wsConnected || !input.trim() || isLoading}
              className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#2d4a3a] to-[#4a7c59] text-white flex items-center justify-center hover:shadow-md disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <p className="text-center text-xs text-[#999] mt-2">Enter 发送，Shift + Enter 换行</p>
        </div>
      </div>
    </div>
  );
}

export default ChatArea;
