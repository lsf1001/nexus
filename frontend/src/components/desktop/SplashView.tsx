import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';

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

  /**
   * 重试:调 Tauri invoke('restart_sidecar') 让 Rust 真正 kill + 重启 PyInstaller
   * sidecar,而**不是** window.location.reload()(那只重载 webview,sidecar 没动)。
   * Rust 重启成功会 emit runtime-status: Ready;失败走 catch 转 Failed。先乐观置
   * Starting 显示 loading,listen 注册在 useEffect 里、模块单例 invoke 不受影响。
   */
  const onRetry = async () => {
    setStatus({ type: 'Starting' });
    try {
      await invoke('restart_sidecar');
      // Rust 会 emit runtime-status: Ready(父组件卸载本组件)/ Failed(listen 更新)
    } catch (e) {
      setStatus({ type: 'Failed', data: `重启失败: ${String(e)}` });
    }
  };

  if (status.type === 'Failed') {
    return (
      <div className="splash splash-error">
        <div className="splash-logo">N</div>
        <h2>后端启动失败</h2>
        <p className="splash-error-msg">{status.data}</p>
        <button className="splash-retry" onClick={onRetry}>
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