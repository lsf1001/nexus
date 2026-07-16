import { useStore } from '../../store';

/**
 * 顶栏浅深色切换 — 2026-07-16 第九轮 UI 重设计。
 *
 * 形态:☀️ / 🌙 单 icon,点一下切换。
 * 数据流:`useStore.uiPrefs.darkMode` ↔ `useDarkModeRoot` (DesktopShell
 * 已挂载) → DOM `data-theme="dark"` attribute。
 *
 * Icon 选择:
 * - 当前浅色(darkMode=false)→ 显示 🌙 表示"点我变深色"
 * - 当前深色(darkMode=true) → 显示 ☀️ 表示"点我变浅色"
 * (与系统设置里"屏幕亮时看月亮,屏幕暗时看太阳"直觉一致)
 */
export function ThemeToggle() {
  const darkMode = useStore((s) => s.darkMode);
  const toggleDarkMode = useStore((s) => s.toggleDarkMode);

  return (
    <button
      type="button"
      className="theme-toggle"
      aria-pressed={darkMode}
      aria-label={darkMode ? '切换到浅色模式' : '切换到深色模式'}
      title={darkMode ? '浅色模式' : '深色模式'}
      onClick={toggleDarkMode}
      data-testid="theme-toggle"
    >
      <span aria-hidden="true">{darkMode ? '☀️' : '🌙'}</span>
    </button>
  );
}
