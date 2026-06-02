import { useState, useEffect, useCallback } from 'react';
import ChatArea from './components/ChatArea';
import ModelConfigModal from './components/ModelConfigModal';
import WechatPluginModal from './components/WechatPluginModal';
import SessionList from './components/SessionList';
import { useStore } from './store/useStore';
import type { Message, SessionResponse, Conversation } from './types';

function App() {
  const [showModelConfig, setShowModelConfig] = useState(false);
  const [showWechatPlugin, setShowWechatPlugin] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(true);
  const [resetCounter, setResetCounter] = useState(0);
  const [wechatConnected, setWechatConnected] = useState(false);
  const darkMode = useStore((s) => s.darkMode);
  const showThinking = useStore((s) => s.showThinking);
  const setDarkMode = useStore((s) => s.setDarkMode);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const clearConversationMessages = useStore((s) => s.clearConversationMessages);
  const setConversationMessages = useStore((s) => s.setConversationMessages);
  const setModelName = useStore((s) => s.setModelName);

  // 加载会话列表
  useEffect(() => {
    loadSessions();
    // 定时刷新会话列表（用于显示后端创建的新会话）
    const timer = setInterval(loadSessions, 3000);
    return () => clearInterval(timer);
  }, []);

  // 定时检查微信连接状态
  useEffect(() => {
    const checkWechatStatus = () => {
      fetch('/api/channels/wechat/bind')
        .then(res => res.json())
        .then((data: { bound: boolean; status?: string }) => {
          setWechatConnected(data.bound && data.status === 'running');
        })
        .catch(() => setWechatConnected(false));
    };
    checkWechatStatus();
    const timer = setInterval(checkWechatStatus, 10000);
    return () => clearInterval(timer);
  }, []);

  const loadSessions = () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);

    fetch('/api/sessions', { signal: controller.signal })
      .then(res => res.json())
      .then((data: SessionResponse[]) => {
        clearTimeout(timeout);
        setConversations(data.map((c: SessionResponse) => ({
          id: c.id,
          title: c.title || '新会话',
          messages: [],
          createdAt: new Date(c.created_at),
          updatedAt: c.updated_at,
          channel: c.channel || 'main',
        })));
      })
      .catch(() => {});
  };

  useEffect(() => {
    fetch('/api/model')
      .then(res => res.json())
      .then(data => {
        if (data.model_name) {
          setModelName(data.model_name);
        }
      })
      .catch(() => {});
  }, [setModelName]);

  const handleLoadConversation = useCallback(async (conv: Conversation) => {
    setCurrentConversationId(conv.id);
    clearConversationMessages();

    // 从后端加载消息
    try {
      const res = await fetch(`/api/sessions/${conv.id}`);
      const data = await res.json();
      const messages: Message[] = (data.messages || []).map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        thinking: m.thinking_content,
        createdAt: new Date(m.created_at),
      }));
      setConversationMessages(messages);
    } catch (e) {
      setConversationMessages(conv.messages);
    }
  }, [clearConversationMessages, setConversationMessages]);

  const handleDeleteConversation = useCallback(async (id: string) => {
    try {
      await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
    } catch (e) {}
    setConversations(prev => prev.filter(c => c.id !== id));
    if (currentConversationId === id) {
      setCurrentConversationId(null);
    }
  }, [currentConversationId]);

  const handleClearCurrent = useCallback(() => {
    setCurrentConversationId(null);
    setResetCounter(c => c + 1);
    clearConversationMessages();
  }, [clearConversationMessages]);

  const toggleDarkMode = () => {
    setDarkMode(!darkMode);
  };

  const handleSessionCreated = useCallback((sessionId: string, title: string) => {
    setCurrentConversationId(sessionId);
    setConversations(prev => [{
      id: sessionId,
      title,
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date().toISOString(),
    }, ...prev]);
  }, []);

  return (
    <div className={`flex h-screen ${darkMode ? 'dark' : ''}`}>
      {/* 左侧边栏 */}
      <aside className={`${showSidebar ? 'w-64' : 'w-0'} h-full min-h-0 flex flex-col ${darkMode ? 'bg-[#0f0f0f] border-[#1f1f1f]' : 'bg-white border-[#e0e5dc]'} border-r transition-all duration-200 overflow-hidden`}>
        <div className="flex items-center gap-3 px-4 py-4 border-b ${darkMode ? 'border-[#1f1f1f]' : 'border-[#e0e5dc]'}">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#4a7c59] to-[#2d4a3a] flex items-center justify-center">
            <span className="text-white font-bold">N</span>
          </div>
          <span className={`${darkMode ? 'text-white' : 'text-[#2d4a3a]'} font-semibold`}>Nexus</span>
        </div>

        {/* 新建会话按钮 */}
        <div className="p-3">
          <button
            onClick={handleClearCurrent}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg ${darkMode ? 'bg-[#1a1a1a] hover:bg-[#252525] text-white' : 'bg-[#f5f7f2] hover:bg-[#e8ece5] text-[#2d4a3a]'} text-sm transition-colors`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            新建会话
          </button>
        </div>

        {/* 历史会话 */}
        <div className="flex-1 overflow-y-auto px-3">
          <div className={`text-xs uppercase px-3 py-2 ${darkMode ? 'text-gray-500' : 'text-[#6b7c6b]'}`}>主会话</div>
          <SessionList
            conversations={conversations}
            channel="main"
            currentConversationId={currentConversationId}
            darkMode={darkMode}
            onSelect={handleLoadConversation}
            onDelete={handleDeleteConversation}
          />

          <div className={`text-xs uppercase px-3 py-2 mt-3 ${darkMode ? 'text-gray-500' : 'text-[#6b7c6b]'}`}>微信会话</div>
          <SessionList
            conversations={conversations}
            channel="wechat"
            currentConversationId={currentConversationId}
            darkMode={darkMode}
            onSelect={handleLoadConversation}
            onDelete={handleDeleteConversation}
          />
        </div>

        {/* 底部设置 */}
        <div className={`p-3 border-t ${darkMode ? 'border-[#1f1f1f]' : 'border-[#e0e5dc]'}`}>
          {/* 显示思考过程开关 */}
          <div className={`flex items-center justify-between px-3 py-2 rounded-lg mb-2 ${darkMode ? 'bg-[#1a1a1a]' : 'bg-[#f0f2ed]'}`}>
            <span className={`text-sm ${darkMode ? 'text-gray-400' : 'text-[#5a6b52]'}`}>显示思考过程</span>
            <button
              onClick={() => setShowThinking(!showThinking)}
              className={`toggle-switch ${showThinking ? '' : 'off'}`}
              aria-label="切换显示思考"
            />
          </div>
          <button
            onClick={() => setShowModelConfig(true)}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${darkMode ? 'hover:bg-[#1a1a1a] text-gray-400' : 'hover:bg-[#f0f2ed] text-[#5a6b52]'}`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            模型配置
          </button>
          <button
            onClick={() => setShowWechatPlugin(true)}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${darkMode ? 'hover:bg-[#1a1a1a] text-gray-400' : 'hover:bg-[#f0f2ed] text-[#5a6b52]'}`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 18h.01M8 21l4-4 4 4M3 4h18M4 4v16l3-3 3 3 3-3 3 3V4" />
            </svg>
            插件管理
          </button>
        </div>
      </aside>

      {/* 主内容区 */}
      <div className="flex-1 flex flex-col bg-[#f5f7f2] overflow-hidden" style={{ minHeight: 0 }}>
        {/* 顶部工具栏 */}
        <header className={`flex items-center justify-between px-4 py-3 ${darkMode ? 'bg-[#0f0f0f] border-[#1f1f1f]' : 'bg-white border-[#e0e5dc]'} border-b`}>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowSidebar(!showSidebar)}
              className={`p-2 rounded-lg transition-colors ${darkMode ? 'hover:bg-[#1a1a1a] text-gray-400' : 'hover:bg-[#f0f2ed] text-[#5a6b52]'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <span className={`${darkMode ? 'text-white' : 'text-[#2d4a3a]'} font-medium`}>聊天</span>
          </div>

          <div className="flex items-center gap-2">
            {/* 颜色模式切换 */}
            <button
              onClick={toggleDarkMode}
              className={`p-2 rounded-lg transition-colors ${darkMode ? 'hover:bg-[#1a1a1a] text-gray-400' : 'hover:bg-[#f0f2ed] text-[#5a6b52]'}`}
              title={darkMode ? '浅色模式' : '深色模式'}
            >
              {darkMode ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
              )}
            </button>

            {/* 连接状态 */}
            <div className="flex items-center gap-2">
              {/* WebSocket 连接 */}
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${darkMode ? 'bg-[#1a1a1a]' : 'bg-[#f0f2ed]'}`}>
                <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-[#4a7c59] animate-pulse' : 'bg-gray-400'}`} />
                <span className={`text-xs ${darkMode ? 'text-gray-400' : 'text-[#5a6b52]'}`}>{wsConnected ? '已连接' : '未连接'}</span>
              </div>
              {/* 微信连接 */}
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${darkMode ? 'bg-[#1a1a1a]' : 'bg-[#f0f2ed]'}`}>
                <div className={`w-2 h-2 rounded-full ${wechatConnected ? 'bg-[#4a7c59] animate-pulse' : 'bg-gray-400'}`} />
                <span className={`text-xs ${darkMode ? 'text-gray-400' : 'text-[#5a6b52]'}`}>微信 {wechatConnected ? '已连接' : '未连接'}</span>
              </div>
            </div>
          </div>
        </header>

        {/* 对话区域 */}
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', flex: 1 }}>
        <ChatArea
          resetTrigger={resetCounter}
          onConnectedChange={setWsConnected}
          conversationId={currentConversationId}
          onSessionCreated={handleSessionCreated}
        />
        </div>
      </div>

      {/* 模型配置弹窗 */}
      <ModelConfigModal
        isOpen={showModelConfig}
        onClose={() => setShowModelConfig(false)}
        onModelChange={setModelName}
      />

      {/* 微信插件弹窗 */}
      <WechatPluginModal
        isOpen={showWechatPlugin}
        onClose={() => setShowWechatPlugin(false)}
        onSuccess={(accountId) => {
          console.log('微信绑定成功:', accountId);
        }}
      />
    </div>
  );
}

export default App;