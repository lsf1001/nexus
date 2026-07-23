/**
 * 可复用代码块组件 — 第十一轮(2026-07-23)复制按钮覆盖。
 *
 * WHY:第九轮 ChatBubble.fenced code block 已经用本地 CodeBlock + 复制按钮
 * 拿到产品级体验,但 ToolCallCard 的 args(JSON)和 result(命令输出 / 文件
 * 内容)是第二高频"用户想复制"的载体(第十轮 ToolCall 透明度提升后尤甚)。
 * 抽出独立组件 + 复用 ChatBubble 的视觉(蓝灰卡 + 右上角复制按钮 + "已复制"
 * 300ms 气泡反馈),让两边一致。
 *
 * 设计:
 *   - text 是唯一输入;language 仅作语义 hint,不做真正语法高亮(留 hooks 给
 *     后续高亮任务;YAGNI,本任务只补复制按钮)
 *   - 复制优先 navigator.clipboard.writeText,失败时 catch + useToastStore.warn
 *     提示用户手动选择(暂不降级 execCommand 'copy' + 临时 textarea — 留
 *     给后续 spec,失败语义只 toast)
 *   - 不打 toast "已复制" 全文(toast 文案短),但保留 300ms "已复制" 微气泡
 *     在按钮旁浮(与 ChatBubble 一致,用户视觉反馈更及时)
 *   - 测试用 navigator.clipboard mock + useToastStore.getState().push mock
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy } from 'lucide-react';
import { useToastStore } from '../../store/useToast';

export interface CodeBlockProps {
  /** 要复制的全文 */
  text: string;
  /** 仅作语义 hint(不强求高亮) */
  language?: string;
  /** 外层容器追加 className(用于 section 内的布局调优) */
  className?: string;
  /** 测试 / 调试用:覆盖 aria-label;默认 "复制内容" */
  ariaLabel?: string;
}

export function CodeBlock({ text, className, ariaLabel = '复制内容' }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).catch((err) => {
        useToastStore
          .getState()
          .push('warn', `复制失败,请手动选择文本 (${err instanceof Error ? err.message : '权限拒绝'})`, 3500);
      });
    } else {
      useToastStore.getState().push('warn', '当前环境不支持剪贴板 API,请手动选择文本', 3500);
    }
    setCopied(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1000);
  }, [text]);

  return (
    <div className={['code-block', className].filter(Boolean).join(' ')}>
      <button
        type="button"
        className="code-copy-btn"
        onClick={onCopy}
        aria-label={ariaLabel}
        title={ariaLabel}
      >
        <Copy size={13} aria-hidden="true" />
      </button>
      {copied && (
        <span className="code-flash" aria-hidden="true">
          已复制
        </span>
      )}
      <pre className="code-pre">
        <code>{text}</code>
      </pre>
    </div>
  );
}

export default CodeBlock;