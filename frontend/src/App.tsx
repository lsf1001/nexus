import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { SplashView, type RuntimeStatus } from './components/desktop/SplashView';

/**
 * Tauri 模式下:监听 runtime-status 事件,sidecar 起来前显示 Splash。
 * 非 Tauri 环境(浏览器 dev):直接进入主界面(此时无 runtime 监听,splash 不显示)。
 */
function App() {
  const [runtimeReady, setRuntimeReady] = useState(
    () => typeof window !== 'undefined' && !('__TAURI_INTERNALS__' in window),
  );

  useEffect(() => {
    // 检测是否在 Tauri 环境中
    const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
    if (!isTauri) {
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

  // runtime 就绪后渲染路由(react-router HashRouter)。Splash/Setup 门控:
  //  - Splash 由上面的 runtimeReady 控制;
  //  - Setup 门控由 router 的 RequireModelConfigured / IndexRedirect 守卫实现,
  //    未配置模型时重定向到 /setup。
  return <RouterProvider router={router} />;
}

export default App;
