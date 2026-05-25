import { useStore } from '../store/useStore';

function Sidebar() {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);

  return (
    <div className="w-64 forest-gradient flex flex-col">
      {/* Logo 区域 */}
      <div className="p-6 flex-shrink-0">
        <h1 className="text-xl font-bold text-[var(--color-wood)] font-serif flex items-center gap-2">
          🌲 Nexus
        </h1>
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