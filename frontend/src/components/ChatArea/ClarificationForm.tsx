/**
 * 澄清表单:LLM 主动追问弹出的卡片。
 *
 * 与 ChatArea 老版本行为完全一致 — Phase 1 拆出独立文件便于维护与(未来)测试。
 * 替换原 ChatArea 文件中的 ClarificationForm 定义,接口不变。
 */

import { useState } from 'react';

export interface ClarificationFormProps {
  question: string;
  options: string[];
  onSubmit: (answer: string) => void;
  onCancel: () => void;
}

export function ClarificationForm({
  question,
  options,
  onSubmit,
  onCancel,
}: ClarificationFormProps) {
  const [freeText, setFreeText] = useState('');
  const hasOptions = options.length > 0;
  const submitFree = () => {
    const value = freeText.trim();
    if (!value) return;
    onSubmit(value);
  };

  return (
    <div className="clarify-card" role="group" aria-label="AI 正在向你确认">
      <div className="clarify-eyebrow">需要你确认</div>
      <div className="clarify-question">{question}</div>
      {hasOptions ? (
        <div className="clarify-options">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              className="clarify-option"
              onClick={() => onSubmit(option)}
            >
              {option}
            </button>
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
              <button
                type="button"
                className="clarify-submit"
                onClick={submitFree}
                disabled={!freeText.trim()}
              >
                发送
              </button>
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
            <button type="button" className="clarify-cancel" onClick={onCancel}>
              取消
            </button>
            <button
              type="button"
              className="clarify-submit"
              onClick={submitFree}
              disabled={!freeText.trim()}
            >
              发送
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
