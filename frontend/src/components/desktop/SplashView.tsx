import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';

export interface RuntimeStatus {
  type: 'Starting' | 'Ready' | 'Failed';
  data?: string;
}

/**
 * 启动 splash: 监听 Rust emit 的 runtime-status 事件。
 * Starting → 显示 loading
 * Ready → 父组件切到主页(此组件由父组件卸载)
 * Failed → 显示错误 + 重试按钮
 */
export function SplashView() {
  const [status, setStatus] = useState<RuntimeStatus>({ type: 'Starting' });

  useEffect(() => {
    let unlistenFn: (() => void) | null = null;

    listen<RuntimeStatus>('runtime-status', (e) => {
      setStatus(e.payload);
    }).then((fn) => {
      unlistenFn = fn;
    });

    return () => {
      if (unlistenFn) unlistenFn();
    };
  }, []);

  if (status.type === 'Failed') {
    return (
      <div className="splash splash-error">
        <div className="splash-logo">N</div>
        <h2>后端启动失败</h2>
        <p className="splash-error-msg">{status.data}</p>
        <button
          className="splash-retry"
          onClick={() => window.location.reload()}
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="splash">
      <div className="splash-logo">N</div>
      <p>正在启动 Nexus...</p>
      <div className="splash-spinner" />
    </div>
  );
}