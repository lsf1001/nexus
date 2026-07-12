/**
 * 错误条 + 重试按钮。
 *
 * ChatArea 老的 error-wrap 段抽出。retryable 走 handleRetry 走上次 user 消息;
 * 非 retryable 仅显示 ✕ 关闭。error code 由 formatErrorMessage 转中文文案。
 */

import { formatErrorMessage } from './constants';
import type { LastError } from './types';

export interface ErrorBannerProps {
  lastError: LastError;
  onRetry: () => void;
  onClose: () => void;
}

export function ErrorBanner({ lastError, onRetry, onClose }: ErrorBannerProps) {
  return (
    <div className="error-wrap">
      <div
        className={`error-banner ${lastError.retryable ? 'is-warn' : 'is-error'}`}
        role="alert"
      >
        <span className="icon">{lastError.retryable ? '⚠️' : '❌'}</span>
        <div className="body">
          <div className="title">{lastError.retryable ? '暂时不可用' : '请求失败'}</div>
          <div className="detail">{formatErrorMessage(lastError.code, lastError.message)}</div>
        </div>
        {lastError.retryable && (
          <button
            type="button"
            className="retry-btn"
            onClick={() => {
              onClose();
              onRetry();
            }}
          >
            重试
          </button>
        )}
        <button
          type="button"
          className="close-btn"
          onClick={onClose}
          aria-label="关闭错误提示"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
