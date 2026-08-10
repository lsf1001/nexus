/**
 * 输入框 / 发送按钮 / 停止按钮 / 文件上传(SPEC §4.1)。
 *
 * 第十三轮(2026-07-24)加附件入口:
 *   - useAttachments(activeProjectId) 维护本地附件列表(图片预览 + 上传状态)
 *   - 提交时把已上传的 server ids 一并交给父组件(ChatArea 拼到 WS / REST 请求)
 *   - + 按钮(file picker,通过 ComposerToolbar.onAttach 回调)+ 整区拖拽 + textarea paste
 *     三路汇入 useAttachments.addFiles
 *   - 拖拽高亮用 dragenter/dragleave 深度计数(dragDepthRef)防子元素冒泡抖动
 *   - onSubmit 签名扩成 (attachmentIds: string[]) => void;
 *     旧调用方传入的空函数 0-arg 仍兼容(TS 函数参数协变,JS 默默丢弃多余实参)
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
 *   - 左侧工具条(附件占位 / 思考开关 / 风格选择器)抽到 ComposerToolbar;
 *     Composer 注入 onAttach 回调把 + 按钮接成 file picker。
 *   - onSubmit 透传 attachmentIds(已 uploaded 的 server id 列表)给 ChatArea。
 *   - onKeyDown 原样透传到 textarea;inputRef 原样传 Textarea。
 *   - textarea.onContextMenu 保持 openContextMenuAt(e, value, '草稿')。
 */

import { useRef, useState, type DragEvent, type ClipboardEvent } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { TooltipProvider } from '@/components/ui/tooltip';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { useStore } from '@/store';
import { AttachmentBar } from './AttachmentBar';
import { ComposerToolbar } from './ComposerToolbar';
import { MicButton } from './MicButton';
import { useAttachments } from './hooks/useAttachments';
import type { RefObject } from 'react';

/**
 * file picker 的 accept 列表。
 *
 * 必须与两层白名单的**交集**保持一致,否则用户能在 picker 里选中却被拒:
 *   - 前端 useAttachments.isAllowedMime:image/* + text/* + application/pdf + application/json
 *   - 后端 attachments.py SUPPORTED_MIMES
 * 这里只列纯 mime、不列扩展名 —— 扩展名(如 .py / .ts)绕过 accept 的 mime 过滤,
 * 但浏览器给出的 file.type 往往为空串或 application/*,反而在 addFiles 里被 reject。
 */
const ACCEPT_ATTR =
  'image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/csv,application/json'

export interface ComposerProps {
  value: string;
  onChange: (next: string) => void;
  /** 提交消息:参数 = 已上传附件的 server id 列表(可空) */
  onSubmit: (attachmentIds: string[]) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  placeholder: string;
  disabled: boolean;
  isLoading: boolean;
  /** 用户主动停止当前流(仅在 isLoading=true 时显示) */
  onStop: () => void;
  /** textarea ref(父组件需要 focus / scroll-into-view) */
  inputRef: RefObject<HTMLTextAreaElement | null>;
  /** 当前会话 id(Round 6.1):透传给 ComposerToolbar 用于风格 PATCH */
  sessionId?: string | null;
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
  sessionId,
}: ComposerProps) {
  const activeProjectId = useStore((s) => s.activeProjectId) ?? 'default';
  const { attachments, addFiles, remove, clear, uploadedServerIds } =
    useAttachments(activeProjectId);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  /** dragenter/dragleave 冒泡深度计数(见 handleDragEnter 注释),放 ref 避免多余重渲染 */
  const dragDepthRef = useRef(0);

  const handleSend = (): void => {
    const serverIds = uploadedServerIds();
    // 提交:即使没有文字,有附件也能发
    if (!value.trim() && serverIds.length === 0) return;
    onSubmit(serverIds);
    clear();
  };

  /**
   * textarea paste:捕获 clipboard.files 转给 useAttachments.addFiles。
   * 不 preventDefault,让 textarea 也接收可能的文字(粘贴板上 text + file 同时存在)。
   */
  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>): void => {
    const files = Array.from(e.clipboardData?.files ?? []);
    if (files.length > 0) addFiles(files);
  };

  /**
   * Composer 整区 dropzone。drop 时取 dataTransfer.files;preventDefault 防浏览器打开文件。
   * drop 结束一次性清零 counter(浏览器不会为 drop 补发对应的 dragleave)。
   */
  const handleDrop = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragging(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length > 0) addFiles(files);
  };

  /**
   * dragenter/dragleave 会从子元素(AttachmentBar / textarea / 按钮)冒泡上来,
   * 光标在子元素之间移动时会收到"离开旧子元素 + 进入新子元素"一对事件。
   * 只看 dragleave 就 setDragging(false) 会让高亮抖动,所以用深度计数:
   * 进入 +1 / 离开 -1,只有归零(真正离开 Composer 整区)才撤高亮。
   */
  const handleDragEnter = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    dragDepthRef.current += 1;
    setDragging(true);
  };

  /**
   * dragover 必须 preventDefault,否则浏览器不认这里是合法 drop 目标(不触发 onDrop)。
   * 同时兜底:若没收到过 dragenter(拖拽中途才挂载 / 测试直接派发 dragover),
   * 把 counter 垫到 1 再置高亮,免得随后第一个子元素 dragleave 就把高亮撤掉。
   */
  const handleDragOver = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    if (dragDepthRef.current === 0) dragDepthRef.current = 1;
    setDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragging(false);
  };

  /** 触发 hidden <input type="file"> click → 用户选文件 → onChange 转 addFiles */
  const openFilePicker = (): void => fileInputRef.current?.click();

  return (
    <TooltipProvider>
      <div className="composer-wrap">
        <div className="composer-shell">
          <div
            className={`composer ${dragging ? 'is-drag-over' : ''}`}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <AttachmentBar attachments={attachments} onRemove={remove} />
            <Textarea
              ref={inputRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={onKeyDown}
              onPaste={handlePaste}
              onContextMenu={(e) => openContextMenuAt(e, value, '草稿')}
              placeholder={placeholder}
              disabled={disabled}
              rows={3}
              className="composer-textarea"
            />
            <div className="composer-bottom">
              <ComposerToolbar onAttach={openFilePicker} sessionId={sessionId ?? undefined} />
              <MicButton
                onTranscribed={(text) => onChange(value ? `${value} ${text}` : text)}
                enabled={!disabled}
              />
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
                  onClick={handleSend}
                  disabled={disabled || (!value.trim() && uploadedServerIds().length === 0)}
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
            {/* hidden file input:ComposerToolbar + 按钮点击触发其 click */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPT_ATTR}
              hidden
              data-testid="composer-file-input"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                if (files.length > 0) addFiles(files);
                // 重置 value 让用户能连续选同一文件(否则 change 不会再次触发)
                e.target.value = ''
              }}
            />
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
