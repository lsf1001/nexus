import React from 'react';
import { invoke } from '@tauri-apps/api/core';

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    // 把完整错误堆栈写到 ~/.nexus/logs/webview-error.log,下次用户报告
    // "应用出现错误"时我能直接读到真错误,不用猜。
    const payload = {
      at: new Date().toISOString(),
      message: error?.message ?? '(no message)',
      stack: error?.stack ?? '(no stack)',
      componentStack: errorInfo?.componentStack ?? '(none)',
      name: error?.name ?? 'Error',
    };
    // Tauri 环境才写文件,浏览器 dev 模式跳过
    const isTauri =
      typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
    if (isTauri) {
      invoke('log_webview_error', { payload: JSON.stringify(payload) }).catch(
        () => {},
      );
    }
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex items-center justify-center min-h-screen bg-red-50">
          <div className="bg-white p-8 rounded-lg shadow-lg max-w-md text-center">
            <div className="text-4xl mb-4">⚠️</div>
            <h2 className="text-xl font-bold text-gray-800 mb-2">应用出现错误</h2>
            <p className="text-gray-600 mb-4">
              {this.state.error?.message || '发生未知错误'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="bg-blue-500 text-white px-6 py-2 rounded hover:bg-blue-600 transition-colors"
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
