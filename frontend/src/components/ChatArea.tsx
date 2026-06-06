import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import { useWebSocket } from '../hooks/useWebSocket';
import ChatBubble from './ChatBubble';
import type { StreamEvent, WSMessage, Message } from '../types';

interface ChatAreaProps {
  resetTrigger?: number;
  onConnectedChange?: (connected: boolean) => void;
  onSessionCreated?: (sessionId: string, title: string) => void;
  conversationId?: string | null;
}

const QUICK_PROMPTS: Array<{ title: string; desc: string; prompt: string }> = [
  { title: '写代码', desc: 'Python、JavaScript...', prompt: '帮我写一段 Python 代码' },
  { title: '分析数据', desc: 'Excel、CSV、JSON...', prompt: '帮我分析这份数据' },
  { title: '知识问答', desc: '解释概念、回答问题...', prompt: '解释一下这个概念' },
  { title: '写作助手', desc: '文章、邮件、报告...', prompt: '帮我写一篇文章' },
];

interface LastError {
  message: string;
  retryable: boolean;
  code: string;
  at: number;
}

function formatErrorMessage(code: string, raw: string): string {
  const map: Record<string, string> = {
    'auth': 'API Key 无效或已过期，请检查配置',
    'rate_limit_exhausted': '请求过于频繁，已重试多次仍失败，请稍后再试',
    'timeout_exhausted': '响应超时，请稍后再试或检查网络',
    'context_length': '对话过长，请开启新会话',
    'content_filter': '内容被安全策略拦截',
    'bad_request': '请求格式有误',
    'agent_unavailable': 'AI 服务暂未启动',
    'invalid_resume_token': '续传凭证已失效',
    'unknown': raw || '未知错误',
  };
  return map[code] ?? raw ?? '未知错误';
}

function ChatArea({ resetTrigger, onConnectedChange, onSessionCreated, conversationId: _conversationId }: ChatAreaProps) {
  const messagesRef = useRef<Message[]>([]);
  const [input, setInput] = useState('');
  const [lastError, setLastError] = useState<LastError | null>(null);
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

  // 注：历史消息加载由 App.tsx 通过 setConversationMessages 完成，本组件无需处理。

  // 处理 WebSocket 消息
  const handleWsMessage = useCallback((raw: StreamEvent | unknown) => {
    const data = raw as StreamEvent;
    if (!data || typeof data !== 'object' || !('type' in data)) return;

    switch (data.type) {
      case 'thinking': {
        if (messagesRef.current.length > 0) {
          const lastIdx = messagesRef.current.length - 1;
          const last = messagesRef.current[lastIdx];
          if (last) {
            last.thinking = (last.thinking || '') + data.content;
            setConversationMessages([...messagesRef.current]);
          }
        }
        break;
      }
      case 'chunk': {
        setLastError(null);  // 流恢复，清掉旧错误（已为 null 时 React 会跳过重渲染）
        if (messagesRef.current.length > 0) {
          const lastIdx = messagesRef.current.length - 1;
          const last = messagesRef.current[lastIdx];
          if (last && last.role === 'assistant') {
            last.content += data.content;
            setConversationMessages([...messagesRef.current]);
          }
        }
        break;
      }
      case 'final': {
        if (messagesRef.current.length > 0) {
          const lastIdx = messagesRef.current.length - 1;
          const last = messagesRef.current[lastIdx];
          if (last) {
            last.content = data.content || '';
            setConversationMessages([...messagesRef.current]);
          }
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
        setLastError({
          message: data.content || '未知错误',
          retryable: data.retryable ?? false,
          code: data.error_code || 'unknown',
          at: Date.now(),
        });
        break;
      }
      case 'wechat_message': {
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
      case 'session_created': {
        onSessionCreated?.(data.session_id || '', data.title || '新会话');
        break;
      }
    }
  }, [onSessionCreated, setConversationMessages, setIsLoading]);

  // WebSocket 连接（含自动重连）
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/api/ws?token=nexus-default-token`;
  const { connected: wsHookConnected, send: wsSend } = useWebSocket<StreamEvent>({
    url: wsUrl,
    onMessage: handleWsMessage,
  });

  // 用 ref 持有最新 send，避免 handleSend 闭包过期
  const sendRef = useRef(wsSend);
  sendRef.current = wsSend;

  // 把 hook 连接状态同步到 store / 父组件
  useEffect(() => {
    setWsConnected(wsHookConnected);
    onConnectedChange?.(wsHookConnected);
  }, [wsHookConnected, setWsConnected, onConnectedChange]);

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
    sendRef.current(msg);
  };

  // 重试最后一条用户消息（错误 UI 中触发）
  const handleRetry = useCallback(() => {
    const lastUserMsg = [...messagesRef.current].reverse().find(m => m.role === 'user');
    if (!lastUserMsg) return;
    setIsLoading(true);
    const msg: WSMessage = { content: lastUserMsg.content };
    if (sessionIdRef.current) msg.session_id = sessionIdRef.current;
    sendRef.current(msg);
  }, [sendRef]);

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
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(content).catch((err) => {
      console.warn('复制失败:', err);
    });
  };

  const bgClass = darkMode ? 'bg-[#0a0a0a]' : 'bg-[#f5f7f2]';
  const inputBgClass = darkMode ? 'bg-[#1a1a1a] border-[#2a2a2a]' : 'bg-white border-[#e0e5dc]';
  const inputTextClass = darkMode ? 'text-white placeholder-gray-500' : 'text-[#2d4a3a] placeholder-[#8a9a7a]';

  return (
    <div className={`flex-1 flex flex-col ${bgClass}`} style={{ minHeight: 0 }}>
      {/* 消息区域 */}
      <div className="chat-scroll flex flex-col flex-1 min-h-0 overflow-y-auto" style={{ minHeight: 0 }}>
        {displayMessages.length === 0 && !isLoading ? (
          /* 欢迎界面 */
          <div className="flex flex-col items-center justify-center px-4">
            <div className="mb-6">
              <img
                src="/totoro.gif"
                alt="龙猫"
                className="w-24 h-24 rounded-2xl object-cover"
              />
            </div>
            <h2 className={`text-2xl font-medium mb-2 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>你好，我是 Nexus</h2>
            <p className={darkMode ? 'text-gray-500 mb-8' : 'text-[#5a6b52] mb-8'}>我可以帮你解答问题、编写代码、分析数据...</p>

            <div className="grid grid-cols-2 gap-3 w-full max-w-md">
              {QUICK_PROMPTS.map(p => (
                <button
                  key={p.title}
                  onClick={() => insertPrompt(p.prompt)}
                  className={`p-4 rounded-xl ${darkMode ? 'bg-[#1a1a1a] hover:bg-[#252525] border-[#2a2a2a]' : 'bg-white hover:bg-[#f5f7f2] border-[#e0e5dc]'} border text-left transition-colors`}
                >
                  <div className={`text-sm font-medium mb-1 ${darkMode ? 'text-white' : 'text-[#2d4a3a]'}`}>{p.title}</div>
                  <div className={`text-xs ${darkMode ? 'text-gray-500' : 'text-[#8a9a7a]'}`}>{p.desc}</div>
                </button>
              ))}
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

      {/* 错误提示（出现在消息区与输入框之间，不抢占输入框） */}
      {lastError && (
        <div className="max-w-3xl mx-auto px-4 pb-2 w-full">
          <div
            className={`p-3 rounded-lg border ${
              lastError.retryable
                ? (darkMode
                    ? 'bg-amber-900/30 border-amber-700 text-amber-200'
                    : 'bg-amber-50 border-amber-300 text-amber-800')
                : (darkMode
                    ? 'bg-red-900/30 border-red-700 text-red-200'
                    : 'bg-red-50 border-red-300 text-red-800')
            }`}
            role="alert"
          >
            <div className="flex items-start gap-2">
              <span className="text-lg leading-none mt-0.5">
                {lastError.retryable ? '⚠️' : '❌'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm">
                  {lastError.retryable ? '暂时不可用' : '请求失败'}
                </div>
                <div className="text-xs mt-0.5 opacity-90 break-words">
                  {formatErrorMessage(lastError.code, lastError.message)}
                </div>
              </div>
              {lastError.retryable && (
                <button
                  onClick={() => {
                    setLastError(null);
                    handleRetry();
                  }}
                  className={`text-xs px-2 py-1 rounded transition-colors flex-shrink-0 ${
                    darkMode
                      ? 'bg-amber-800 hover:bg-amber-700 text-amber-100'
                      : 'bg-amber-200 hover:bg-amber-300 text-amber-900'
                  }`}
                >
                  重试
                </button>
              )}
              <button
                onClick={() => setLastError(null)}
                className="text-xs opacity-60 hover:opacity-100 transition-opacity flex-shrink-0"
                aria-label="关闭错误提示"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 输入区域 */}
      <div className={`p-4 border-t flex-shrink-0 ${darkMode ? 'border-[#1f1f1f] bg-[#0f0f0f]' : 'border-[#e0e5dc] bg-white'}`} style={{ flex: '0 0 auto' }}>
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