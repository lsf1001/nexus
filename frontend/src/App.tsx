import { useState, useEffect } from 'react';
import ChatArea from './components/ChatArea';
import ModelConfigModal from './components/ModelConfigModal';
import totoroGif from './assets/totoro.gif';

function App() {
  const [showModelConfig, setShowModelConfig] = useState(false);
  const [modelName, setModelName] = useState('MiniMax-M2.7');
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    // 获取当前模型
    fetch('/api/model')
      .then(res => res.json())
      .then(data => {
        if (data.model_name) {
          setModelName(data.model_name);
        }
      })
      .catch(() => {});
  }, []);

  return (
    <div className="flex flex-col h-screen bg-[#faf8f5]">
      {/* 顶部导航 */}
      <header className="flex items-center justify-between px-6 py-4 bg-white/80 backdrop-blur-md border-b border-[#e8e4dc]">
        <div className="flex items-center gap-3">
          <img
            src={totoroGif}
            alt="龙猫"
            className="w-10 h-10 rounded-xl object-cover shadow-sm"
          />
          <span className="text-lg font-semibold text-[#2d4a3a] tracking-tight">Nexus</span>
        </div>

        <div className="flex items-center gap-4">
          {/* 模型选择 */}
          <button
            onClick={() => setShowModelConfig(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-full bg-[#faf8f5] border border-[#e0dcd4] hover:border-[#4a7c59] hover:bg-white transition-all"
          >
            <span className="text-sm font-medium text-[#4a7c59]">{modelName}</span>
            <svg className="w-4 h-4 text-[#6b7c6b]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {/* 连接状态 */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#2d4a3a]/10">
            <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-[#4a7c59] animate-pulse' : 'bg-gray-400'}`} />
            <span className="text-xs font-medium text-[#2d4a3a]">{wsConnected ? '已连接' : '未连接'}</span>
          </div>
        </div>
      </header>

      {/* 对话区域 */}
      <ChatArea onConnectedChange={setWsConnected} />

      {/* 模型配置弹窗 */}
      <ModelConfigModal
        isOpen={showModelConfig}
        onClose={() => setShowModelConfig(false)}
        onModelChange={setModelName}
      />
    </div>
  );
}

export default App;
