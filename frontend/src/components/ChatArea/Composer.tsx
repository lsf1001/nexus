/**
 * 输入框 / 发送按钮 / 停止按钮。
 *
 * 拆出原因:composer-wrap 内 textarea + send 按钮占 50 行,与 ChatArea 业务编排无关。
 * 这里只暴露外部控制的 value + onChange + onSubmit + placeholder + disabled 模式。
 *
 * 流期间按钮切换(2026-07-13):
 *   isLoading=true 时 send 按钮被替换为 stop 按钮,触发 onStop。
 *   点 stop → ChatArea 把当前流标"用户停止",后续 chunk 被客户端 gate 掉
 *   (useChatStream.stoppedRef),不再写 store;同时 disarmWatchdog + 改 isLoading=false。
 *   服务端流仍继续到自然结束(后端无 abort 帧),但客户端只看到"[已停止]" marker
 *   + 之前已渲染的内容,体感上是即时停止。
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
  /** 用户主动停止当前流(仅在 isLoading=true 时显示) */
  onStop: () => void;
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
  onStop,
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
            <button
              type="button"
              className="composer-plus"
              aria-label="添加附件 / 截图 / 选 skill"
              title="添加附件 · 截图 · 选 skill(后续版本开放)"
              onClick={() => {
                /* 第九轮占位:无行为,后续 PR 加附件 / 截图 / skill 选择 */
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </button>
            <span className="hint">
              {isLoading ? '正在生成中...可点击右侧按钮停止' : '个人任务助手 · 本地运行'}
            </span>
            {isLoading ? (
              <button
                type="button"
                onClick={onStop}
                className="send-button stop-button"
                aria-label="停止生成"
                title="停止当前回复生成"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              </button>
            ) : (
              <button
                type="button"
                onClick={onSubmit}
                disabled={disabled || !value.trim()}
                className="send-button"
                aria-label="发送消息"
                title="发送消息"
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
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
