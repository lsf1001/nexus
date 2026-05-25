import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';

function Sidebar() {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const models = useStore((s) => s.models);
  const currentModelId = useStore((s) => s.currentModelId);
  const setModels = useStore((s) => s.setModels);
  const setCurrentModelId = useStore((s) => s.setCurrentModelId);
  const setModelName = useStore((s) => s.setModelName);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const apiUrl = 'http://localhost:8000/api';

  useEffect(() => {
    fetch(`${apiUrl}/models`)
      .then(res => res.json())
      .then(data => {
        setModels(data);
        const active = data.find((m: { is_active: boolean }) => m.is_active);
        if (active) {
          setCurrentModelId(active.id);
          setModelName(active.name);
        }
      })
      .catch(console.error);
  }, []);

  const handleSwitchModel = async (modelId: string) => {
    try {
      const res = await fetch(`${apiUrl}/models/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: modelId }),
      });
      const data = await res.json();
      if (data.success) {
        setCurrentModelId(data.active_model.id);
        setModelName(data.active_model.name);
        setIsDropdownOpen(false);
      }
    } catch (err) {
      console.error('切换模型失败:', err);
    }
  };

  const currentModel = models.find(m => m.id === currentModelId);

  return (
    <div className="w-64 forest-gradient flex flex-col">
      {/* Logo 区域 */}
      <div className="p-6 flex-shrink-0">
        <h1 className="text-xl font-bold text-[var(--color-wood)] font-serif flex items-center gap-2">
          🌲 Nexus
        </h1>
      </div>

      {/* 模型选择器 */}
      <div className="px-4 pb-4 flex-shrink-0">
        <div className="bg-white/10 backdrop-blur-sm rounded-2xl p-3">
          <div className="text-xs text-[var(--color-moss-light)] mb-2">当前模型</div>
          <div className="relative">
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className="w-full px-3 py-2 bg-white/20 rounded-xl text-sm text-[var(--color-wood)] flex items-center justify-between hover:bg-white/30 transition-colors"
            >
              <span>{currentModel?.name || '选择模型'}</span>
              <span className="text-xs">{isDropdownOpen ? '▲' : '▼'}</span>
            </button>
            {isDropdownOpen && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl shadow-lg overflow-hidden z-10">
                {models.map(model => (
                  <button
                    key={model.id}
                    onClick={() => handleSwitchModel(model.id)}
                    className={`w-full px-3 py-2 text-sm text-left hover:bg-gray-100 transition-colors ${
                      model.id === currentModelId ? 'bg-[var(--color-moss)]/20 text-[var(--color-moss)]' : 'text-gray-700'
                    }`}
                  >
                    {model.name}
                    {model.id === currentModelId && ' ✓'}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 龙猫 GIF 区域 - 占据上方大空间 */}
      <div className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="w-40 h-40 rounded-2xl overflow-hidden bg-[var(--color-cream)] shadow-[0_8px_32px_rgba(0,0,0,0.3)]">
          <img
            src="/totoro-new.gif"
            alt="龙猫"
            className="w-full h-full object-cover"
          />
        </div>
      </div>

      {/* Toggle 开关 */}
      <div className="p-4 flex-shrink-0">
        <div className="bg-white/10 backdrop-blur-sm rounded-2xl p-4">
          <div className="text-xs text-[var(--color-moss-light)] mb-3">显示思考过程</div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowThinking(!showThinking)}
              className={`toggle-switch ${showThinking ? '' : 'off'}`}
              aria-label="切换显示思考"
            />
            <span className="text-xs text-[var(--color-wood)]">
              {showThinking ? 'ON' : 'OFF'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Sidebar;
