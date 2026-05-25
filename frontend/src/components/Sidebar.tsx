import { useStore } from '../store/useStore';

function Sidebar() {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);

  return (
    <div className="w-64 forest-gradient flex flex-col relative">
      {/* Logo 区域 */}
      <div className="p-6">
        <h1 className="text-xl font-bold text-[var(--color-wood)] font-serif flex items-center gap-2">
          🌲 Nexus
        </h1>
      </div>

      {/* 中间区域 */}
      <div className="flex-1" />

      {/* 龙猫 Mascot */}
      <div className="totoro-mascot">
        <img
          src="https://media.giphy.com/media/26FPy3QZQqGtDcr6U/giphy.gif"
          alt="龙猫"
        />
        <div className="text-xs text-[var(--color-moss-light)] mt-1">森林精灵</div>
      </div>

      {/* Toggle 开关 */}
      <div className="p-4">
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