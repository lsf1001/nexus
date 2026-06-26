import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { DesktopShell } from './components/desktop/DesktopShell';
import { SplashView, RuntimeStatus } from './components/desktop/SplashView';

/**
 * Tauri 模式下:监听 runtime-status 事件,sidecar 起来前显示 Splash。
 * 非 Tauri 环境(浏览器 dev):直接进入主界面(此时无 runtime 监听,splash 不显示)。
 */
function App() {
  const [runtimeReady, setRuntimeReady] = useState(false);

  useEffect(() => {
    // 检测是否在 Tauri 环境中
    const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
    if (!isTauri) {
      // 浏览器 dev 模式:直接进入主界面
      setRuntimeReady(true);
      return;
    }

    let unlistenFn: (() => void) | null = null;
    listen<RuntimeStatus>('runtime-status', (e) => {
      if (e.payload.type === 'Ready') setRuntimeReady(true);
    }).then((fn) => {
      unlistenFn = fn;
    });

    return () => {
      if (unlistenFn) unlistenFn();
    };
  }, []);

  if (!runtimeReady) return <SplashView />;

  return <DesktopShell />;
}

export default App;