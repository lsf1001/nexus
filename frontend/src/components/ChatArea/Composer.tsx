/**
 * 输入框 / 发送按钮。
 *
 * 拆出原因:composer-wrap 内 textarea + send 按钮占 50 行,与 ChatArea 业务编排无关。
 * 这里只暴露外部控制的 value + onChange + onSubmit + placeholder + disabled 模式。
 */

import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import type { RefObject } from 'react';

export interface ComposerProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  placeholder: string;
  disabled: boolean;
  isLoading: boolean;
  /** textarea ref(父组件需要 focus / scroll-into-view) */
  inputRef: RefObject<HTMLTextAreaElement | null>;
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onKeyDown,
  placeholder,
  disabled,
  isLoading,
  inputRef,
}: ComposerProps) {
  return (
    <div className="composer-wrap">
      <div className="composer-shell">
        <div className="composer">
          <textarea
            ref={inputRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            onContextMenu={(e) => openContextMenuAt(e, value, '草稿')}
            placeholder={placeholder}
            disabled={disabled}
            rows={3}
            className="composer-textarea"
          />
          <div className="composer-bottom">
            <span className="hint">
              {isLoading ? '正在生成中...可继续输入下一条' : '个人任务助手 · 本地运行'}
            </span>
            <button
              type="button"
              onClick={onSubmit}
              disabled={disabled || !value.trim() || isLoading}
              className="send-button"
              aria-label="发送消息"
              title={isLoading ? '请等待当前回复完成' : '发送消息'}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
