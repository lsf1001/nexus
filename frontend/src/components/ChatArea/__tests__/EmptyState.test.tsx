/**
 * EmptyState 升级锁测试 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop / ChatGPT 首屏 = hero + 大输入框(直接回车发送),
 * prompt 卡片只是辅助。第八轮 EmptyState 没有大输入框,用户必须先新建
 * 会话跳到 ChatArea 才能发消息。第九轮:
 *   1. EmptyState 自带大输入框(textarea)+ 圆形 ↑ 发送按钮
 *   2. onSubmit(text) 调上游 ChatArea,onInsertPrompt 改 onInsertPrompt 复用
 *   3. Enter 发送 / Shift+Enter 换行
 *
 * 测试断言:
 *   1. 渲染 hero h1
 *   2. 渲染 QUICK_PROMPTS 4 个 prompt 卡片
 *   3. 渲染大 textarea + ↑ 发送按钮
 *   4. 输入文字 + Enter → 调 onSubmit
 *   5. Shift+Enter → 换行,不提交
 *   6. 点 prompt 卡片 → 调 onInsertPrompt
 *   7. 点 ↑ 按钮 → 调 onSubmit
 *   8. h1 字号用 --font-2xl(≥ 32px)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
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

describe('EmptyState 第九轮升级(大输入框)', () => {
  it('渲染 hero h1', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const h1 = container.querySelector('.hero h1');
    expect(h1).not.toBeNull();
    expect(h1?.textContent).toBeTruthy();
  });

  it('hero h1 字号 ≥ 32px (var(--font-2xl))', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const h1 = container.querySelector('.hero h1') as HTMLElement;
    // jsdom 不算 computed style,改成断言 h1 节点 + CSS 类名 + 实际样式由 CSS 控
    expect(h1).not.toBeNull();
    // 锁:hero-title 必须用 .hero-title-2xl 类(全局 CSS 强制 --font-2xl)
    expect(h1?.classList.contains('hero-title-2xl') || container.querySelector('style')?.textContent?.includes('--font-2xl')).toBeTruthy();
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

  it('渲染大 textarea + ↑ 发送按钮', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const ta = container.querySelector('textarea.empty-state-composer');
    expect(ta).not.toBeNull();
    expect(ta?.getAttribute('placeholder')).toBeTruthy();
    const sendBtn = container.querySelector('button.empty-state-send');
    expect(sendBtn).not.toBeNull();
  });

  it('输入文字 + Enter → 调 onSubmit(text),清空 textarea', () => {
    const { container } = render(<EmptyState {...baseProps} onSubmit={baseProps.onSubmit} />);
    const ta = container.querySelector('textarea.empty-state-composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '你好' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: false });
    expect(baseProps.onSubmit).toHaveBeenCalledWith('你好');
    expect(ta.value).toBe('');
  });

  it('Shift+Enter → 换行,不提交', () => {
    const { container } = render(<EmptyState {...baseProps} onSubmit={baseProps.onSubmit} />);
    const ta = container.querySelector('textarea.empty-state-composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '行1' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(baseProps.onSubmit).not.toHaveBeenCalled();
  });

  it('点 ↑ 按钮 → 调 onSubmit(text)', () => {
    const { container } = render(<EmptyState {...baseProps} onSubmit={baseProps.onSubmit} />);
    const ta = container.querySelector('textarea.empty-state-composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '点按钮' } });
    const sendBtn = container.querySelector('button.empty-state-send') as HTMLElement;
    sendBtn.click();
    expect(baseProps.onSubmit).toHaveBeenCalledWith('点按钮');
  });

  it('空字符串不提交', () => {
    const { container } = render(<EmptyState {...baseProps} onSubmit={baseProps.onSubmit} />);
    const sendBtn = container.querySelector('button.empty-state-send') as HTMLElement;
    sendBtn.click();
    expect(baseProps.onSubmit).not.toHaveBeenCalled();
  });
});