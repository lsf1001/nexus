/**
 * EmptyState 锁测试 — 引导页(hero + prompt 卡片 + 状态卡)。
 *
 * 输入框已统一到底部 Composer(ChatArea 层渲染),EmptyState 只负责引导内容:
 *   1. hero 区(eyebrow + h1 标题 + 副标题)
 *   2. QUICK_PROMPTS prompt 卡片网格(点击 → onInsertPrompt)
 *   3. 任务状态卡(显示模型/连接/会话/计数)
 *
 * 测试断言:
 *   1. 渲染 hero h1
 *   2. h1 字号用 hero-title-2xl 类
 *   3. 渲染 QUICK_PROMPTS 4 个 prompt 卡片
 *   4. 点 prompt 卡片 → 调 onInsertPrompt(prompt text)
 *   5. 不再自带 textarea / 发送按钮(统一由 Composer 处理)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { EmptyState } from '../EmptyState';
import { QUICK_PROMPTS } from '../constants';

const baseProps = {
  modelName: 'test-model',
  connectionState: 'online' as const,
  activeConversationTitle: null,
  conversationCount: 0,
  onInsertPrompt: vi.fn(),
  onSubmit: vi.fn(),
};

beforeEach(() => {
  baseProps.onInsertPrompt.mockClear();
  baseProps.onSubmit.mockClear();
});

describe('EmptyState 引导页', () => {
  it('渲染 hero h1', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const h1 = container.querySelector('.hero h1');
    expect(h1).not.toBeNull();
    expect(h1?.textContent).toBeTruthy();
  });

  it('hero h1 用 hero-title-2xl 类(大字号)', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const h1 = container.querySelector('.hero h1') as HTMLElement;
    expect(h1).not.toBeNull();
    expect(h1?.classList.contains('hero-title-2xl')).toBeTruthy();
  });

  it(`渲染 ${QUICK_PROMPTS.length} 个 prompt 卡片`, () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const cards = container.querySelectorAll('.prompt-card');
    expect(cards.length).toBe(QUICK_PROMPTS.length);
  });

  it('点 prompt 卡片 → 调 onInsertPrompt(prompt text)', () => {
    const { container } = render(<EmptyState {...baseProps} onInsertPrompt={baseProps.onInsertPrompt} />);
    const first = container.querySelector('.prompt-card') as HTMLElement;
    first.click();
    expect(baseProps.onInsertPrompt).toHaveBeenCalledWith(QUICK_PROMPTS[0]!.prompt);
  });

  it('渲染任务状态卡(含模型名和连接状态)', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const statusCard = container.querySelector('.status-card');
    expect(statusCard).not.toBeNull();
    expect(statusCard?.textContent).toContain('test-model');
  });

  it('不再自带 textarea 或发送按钮(统一由底部 Composer 处理)', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const ta = container.querySelector('textarea.empty-state-composer');
    expect(ta).toBeNull();
    const sendBtn = container.querySelector('button.empty-state-send');
    expect(sendBtn).toBeNull();
  });
});
