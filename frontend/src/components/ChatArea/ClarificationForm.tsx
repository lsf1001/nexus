/**
 * 澄清表单:LLM 主动追问弹出的卡片。
 *
 * 与 ChatArea 老版本行为完全一致 — Phase 1 拆出独立文件便于维护与(未来)测试。
 * 替换原 ChatArea 文件中的 ClarificationForm 定义,接口不变。
 *
 * 2026-07-14 UX 兜底:
 *   LLM 偶尔不传 options(违反 prompt 强约束),fallback 到纯 textarea 体感差。
 *   这里在 options 为空时塞 2 个"AI 帮我想"候选 + 一条"自定义"按钮,
 *   保证用户至少有"点一下就走"的按钮 UX,而不是面对空白输入框发懵。
 *   后端 streaming.py 会打 warning log 让我们知道这是 fallback 路径。
 */

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface ClarificationFormProps {
  question: string;
  options: string[];
  onSubmit: (answer: string) => void;
  onCancel: () => void;
}

/** Fallback 候选(2026-07-14):LLM 没传 options 时塞这两个按钮。 */
const FALLBACK_OPTIONS: readonly string[] = ['让 Nexus 帮我想', '我需要更多信息'];

export function ClarificationForm({
  question,
  options,
  onSubmit,
  onCancel,
}: ClarificationFormProps) {
  const [freeText, setFreeText] = useState('');
  // 兜底:options 为空时塞 2 个候选,让 UI 一定有按钮(主流 ChatGPT / Claude.ai 同款)。
  const effectiveOptions = options.length > 0 ? options : [...FALLBACK_OPTIONS];
  const submitFree = () => {
    const value = freeText.trim();
    if (!value) return;
    onSubmit(value);
  };

  return (
    <div className="clarify-card" role="group" aria-label="AI 正在向你确认">
      <div className="clarify-eyebrow">需要你确认</div>
      <div className="clarify-question">{question}</div>
      {effectiveOptions.length > 0 ? (
        <div className="clarify-options">
          {effectiveOptions.map((option) => (
            <Button
              key={option}
              type="button"
              className={cn('clarify-option', 'w-full justify-start text-left')}
              onClick={() => onSubmit(option)}
            >
              {option}
            </Button>
          ))}
          <details className="clarify-free-toggle">
            <summary>自己写回答</summary>
            <div className="clarify-free">
              <textarea
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                placeholder="输入你的回答..."
                rows={2}
                className="clarify-textarea"
              />
              <Button
                type="button"
                className={cn('clarify-submit')}
                onClick={submitFree}
                disabled={!freeText.trim()}
              >
                发送
              </Button>
            </div>
          </details>
        </div>
      ) : (
        <div className="clarify-free">
          <textarea
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder="输入你的回答..."
            rows={3}
            className="clarify-textarea"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitFree();
              }
            }}
          />
          <div className="clarify-actions">
            <Button type="button" className={cn('clarify-cancel')} onClick={onCancel}>
              取消
            </Button>
            <Button
              type="button"
              className={cn('clarify-submit')}
              onClick={submitFree}
              disabled={!freeText.trim()}
            >
              发送
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
