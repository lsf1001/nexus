/**
 * 输入框 / 发送按钮 / 停止按钮(Claude 范式重建,Task 3.2)。
 *
 * 拆出原因:composer-wrap 内 textarea + send 按钮与 ChatArea 业务编排无关。
 * 这里只暴露外部控制的 value + onChange + onSubmit + placeholder + disabled 模式。
 *
 * 流期间按钮切换:isLoading=true 时 send 按钮被替换为 stop 按钮,触发 onStop。
 *   点 stop → ChatArea 把当前流标"用户停止",后续 chunk 被客户端 gate 掉
 *   (useChatStream.stoppedRef),不再写 store;同时 disarmWatchdog + 改 isLoading=false。
 *
 * 重建要点:
 *   - 用 shadcn Textarea / Button / TooltipProvider 替换原生元素,守住测试锁定类名
 *     (composer-wrap/shell/composer/textarea/bottom/hint/send-button/stop-button/composer-plus)。
 *   - 左侧工具条(附件占位 / 思考开关 / 风格选择器)抽到 ComposerToolbar。
 *   - ComposerProps 接口一字不改;onKeyDown 原样透传到 textarea;inputRef 原样传
 *     Textarea(其底层渲染原生 <textarea>,forwardRef 链完整)。
 *   - textarea.onContextMenu 保持 openContextMenuAt(e, value, '草稿')。
 */

import { Textarea } from '@/components/ui/textarea';
import { TooltipProvider } from '@/components/ui/tooltip';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import type { RefObject } from 'react';
import { ComposerToolbar } from './ComposerToolbar';

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
    <TooltipProvider>
      <div className="composer-wrap">
        <div className="composer-shell">
          <div className="composer">
            <Textarea
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
              <ComposerToolbar />
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
    </TooltipProvider>
  );
}
