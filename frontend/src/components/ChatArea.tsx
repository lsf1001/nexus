import { useState, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import ChatBubble from './ChatBubble';
import totoroGif from '../assets/totoro.gif';
import type { StreamEvent, WSMessage, Message } from '../types';

interface ChatAreaProps {
  resetTrigger?: number;
  onConnectedChange?: (connected: boolean) => void;
  onSaveConversation?: (messages: Message[]) => void;
  conversationId?: string | null;
}

function ChatArea({ resetTrigger, onConnectedChange, conversationId: _conversationId }: ChatAreaProps) {
  const wsRef = useRef<WebSocket | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const resetTriggerRef = useRef(resetTrigger ?? 0);
  // 使用 ref 跟踪 session_id，因为 React state 更新是异步的
  const sessionIdRef = useRef<string | null>(_conversationId);

  // 当 conversationId prop 变化时，同步更新 ref
  useEffect(() => {
    sessionIdRef.current = _conversationId;
  }, [_conversationId]);

  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const showThinking = useStore((s) => s.showThinking);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const darkMode = useStore((s) => s.darkMode);
  const displayMessages = useStore((s) => s.conversationMessages);
  const setConversationMessages = useStore((s) => s.setConversationMessages);
  const clearConversationMessages = useStore((s) => s.clearConversationMessages);

  // 当 resetTrigger 变化时，重置所有消息状态
  useEffect(() => {
    if (resetTrigger && resetTrigger > resetTriggerRef.current) {
      messagesRef.current = [];
      clearConversationMessages();
      setInput('');
    }
    resetTriggerRef.current = resetTrigger ?? 0;
  }, [resetTrigger, clearConversationMessages]);

  // 当 conversationId 有值时（从历史加载），加载对应消息
  useEffect(() => {
    if (_conversationId) {
      // 消息已在 App.tsx 通过 setConversationMessages 设置
    }
  }, [_conversationId]);

  // WebSocket 连接
  useEffect(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/api/ws?token=nexus-default-token`;
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
            setConversationMessages([...messagesRef.current]);
          }
          break;
        }
        case 'chunk': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            if (messagesRef.current[lastIdx].role === 'assistant') {
              messagesRef.current[lastIdx].content += data.content;
            }
            setConversationMessages([...messagesRef.current]);
          }
          break;
        }
        case 'final': {
          if (messagesRef.current.length > 0) {
            const lastIdx = messagesRef.current.length - 1;
            messagesRef.current[lastIdx].content = data.content || '';
            setConversationMessages([...messagesRef.current]);
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
        case 'wechat_message': {
          // 处理微信消息
          const wechatMsg: Message = {
            id: crypto.randomUUID(),
            role: 'user',
            content: data.content || '',
            createdAt: new Date(),
          };
          messagesRef.current.push(wechatMsg);
          setConversationMessages([...messagesRef.current]);
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
    setConversationMessages([...messagesRef.current]);

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
    };
    messagesRef.current.push(assistantMsg);
    setConversationMessages([...messagesRef.current]);

    const msg: WSMessage = { content: messageContent };
    // 如果没有 session_id，发送 title 让后端创建会话
    if (!sessionIdRef.current) {
      msg.title = messageContent.slice(0, 30);  // 作为会话标题
    } else {
      msg.session_id = sessionIdRef.current;
    }
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

  const handleCopyMessage = (content: string) => {
    navigator.clipboard.writeText(content).then(() => {});
  };

  const bgClass = darkMode ? 'bg-[#0a0a0a]' : 'bg-[#f5f7f2]';
  const inputBgClass = darkMode ? 'bg-[#1a1a1a] border-[#2a2a2a]' : 'bg-white border-[#e0e5dc]';
  const inputTextClass = darkMode ? 'text-white placeholder-gray-500' : 'text-[#2d4a3a] placeholder-[#8a9a7a]';

  return (
    <div className={`flex-1 flex flex-col ${bgClass}`}>
      {/* 消息区域 */}
      <div className="flex-1 overflow-y-auto">
        {displayMessages.length === 0 && !isLoading ? (
          /* 欢迎界面 */
          <div className="flex flex-col items-center justify-center h-full px-4">
            <div className="mb-6">
              <img
                src={totoroGif}
                alt="龙猫"
                className="w-24 h-24 rounded-2xl object-cover"
              />
            </div>
            <h2 className={`text-2xl font-medium mb-2 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>你好，我是 Nexus</h2>
            <p className={darkMode ? 'text-gray-500 mb-8' : 'text-[#5a6b52] mb-8'}>我可以帮你解答问题、编写代码、分析数据...</p>

            <div className="grid grid-cols-2 gap-3 w-full max-w-md">
              <button
                onClick={() => insertPrompt('帮我写一段 Python 代码')}
                className={`p-4 rounded-xl ${darkMode ? 'bg-[#1a1a1a] hover:bg-[#252525] border-[#2a2a2a]' : 'bg-white hover:bg-[#f5f7f2] border-[#e0e5dc]'} border text-left transition-colors`}
              >
                <div className={`text-sm font-medium mb-1 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>写代码</div>
                <div className={`text-xs ${darkMode ? 'text-gray-500' : 'text-[#8a9a7a]'}`}>Python、JavaScript...</div>
              </button>
              <button
                onClick={() => insertPrompt('帮我分析这份数据')}
                className={`p-4 rounded-xl ${darkMode ? 'bg-[#1a1a1a] hover:bg-[#252525] border-[#2a2a2a]' : 'bg-white hover:bg-[#f5f7f2] border-[#e0e5dc]'} border text-left transition-colors`}
              >
                <div className={`text-sm font-medium mb-1 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>分析数据</div>
                <div className={`text-xs ${darkMode ? 'text-gray-500' : 'text-[#8a9a7a]'}`}>Excel、CSV、JSON...</div>
              </button>
              <button
                onClick={() => insertPrompt('解释一下这个概念')}
                className={`p-4 rounded-xl ${darkMode ? 'bg-[#1a1a1a] hover:bg-[#252525] border-[#2a2a2a]' : 'bg-white hover:bg-[#f5f7f2] border-[#e0e5dc]'} border text-left transition-colors`}
              >
                <div className={`text-sm font-medium mb-1 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>知识问答</div>
                <div className={`text-xs ${darkMode ? 'text-gray-500' : 'text-[#8a9a7a]'}`}>解释概念、回答问题...</div>
              </button>
              <button
                onClick={() => insertPrompt('帮我写一篇文章')}
                className={`p-4 rounded-xl ${darkMode ? 'bg-[#1a1a1a] hover:bg-[#252525] border-[#2a2a2a]' : 'bg-white hover:bg-[#f5f7f2] border-[#e0e5dc]'} border text-left transition-colors`}
              >
                <div className={`text-sm font-medium mb-1 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>写作助手</div>
                <div className={`text-xs ${darkMode ? 'text-gray-500' : 'text-[#8a9a7a]'}`}>文章、邮件、报告...</div>
              </button>
            </div>
          </div>
        ) : (
          /* 对话消息 */
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
            {displayMessages.map((msg) => (
              <ChatBubble
                key={msg.id}
                message={msg}
                showThinking={showThinking}
                onCopy={handleCopyMessage}
              />
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className={`${darkMode ? 'bg-[#1a1a1a] border-[#2a2a2a]' : 'bg-white border-[#e0e5dc]'} px-4 py-3 rounded-2xl border`}>
                  <div className="flex gap-1">
                    <span className={`w-2 h-2 rounded-full ${darkMode ? 'bg-gray-500' : 'bg-[#4a7c59]'} animate-bounce`} style={{ animationDelay: '0ms' }} />
                    <span className={`w-2 h-2 rounded-full ${darkMode ? 'bg-gray-500' : 'bg-[#4a7c59]'} animate-bounce`} style={{ animationDelay: '150ms' }} />
                    <span className={`w-2 h-2 rounded-full ${darkMode ? 'bg-gray-500' : 'bg-[#4a7c59]'} animate-bounce`} style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className={`p-4 border-t ${darkMode ? 'border-[#1f1f1f] bg-[#0f0f0f]' : 'border-[#e0e5dc] bg-white'}`}>
        <div className="max-w-3xl mx-auto">
          <div className={`flex items-end gap-3 ${inputBgClass} rounded-xl border px-4 py-3 focus-within:border-[#4a7c59] transition-colors`}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={wsConnected ? '输入消息...' : '连接中...'}
              disabled={!wsConnected || isLoading}
              rows={1}
              className={`flex-1 bg-transparent resize-none focus:outline-none ${inputTextClass} disabled:${darkMode ? 'text-gray-600' : 'text-[#c0c0b0]'}`}
            />
            <button
              onClick={handleSend}
              disabled={!wsConnected || !input.trim() || isLoading}
              className={`w-9 h-9 rounded-lg bg-[#4a7c59] text-white flex items-center justify-center hover:bg-[#5a8c69] disabled:opacity-40 disabled:cursor-not-allowed transition-colors`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <p className={`text-center text-xs mt-2 ${darkMode ? 'text-gray-600' : 'text-[#a0a090]'}`}>Enter 发送，Shift + Enter 换行</p>
        </div>
      </div>
    </div>
  );
}

export default ChatArea;