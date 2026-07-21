/**
 * EmptyState 锁测试 — 引导页(hero 标题 + 描述 + 速记 chip 横向布局)。
 *
 * 简化后(2026-07-21)EmptyState 只负责引导内容:
 *   1. hero h1 标题(hero-title-2xl 大字号)
 *   2. 副标题描述(text-sm ≈ 14px)
 *   3. QUICK_PROMPTS 4 个 prompt chip 横向排列(点击 → onInsertPrompt)
 *
 * 已移除:eyebrow"个人任务助手" / 任务状态卡(.status-card,顶部状态栏已重复)。
 *
 * 测试断言(三类路径):
 *   正常:渲染 h1(hero-title-2xl)、渲染 4 个 prompt-card、点击回调
 *   边界:.prompt-row 横向容器存在、不再渲染 .status-card / .eyebrow
 *   异常:不自带 textarea / 发送按钮(统一由底部 Composer 处理)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { EmptyState } from '../EmptyState';
import { QUICK_PROMPTS } from '../constants';

const baseProps = {
  onInsertPrompt: vi.fn(),
};

beforeEach(() => {
  baseProps.onInsertPrompt.mockClear();
});

describe('EmptyState 引导页', () => {
  it('渲染 hero h1', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const h1 = container.querySelector('h1');
    expect(h1).not.toBeNull();
    expect(h1?.textContent).toBeTruthy();
  });

  it('hero h1 用 hero-title-2xl 类(大字号)', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const h1 = container.querySelector('h1') as HTMLElement;
    expect(h1).not.toBeNull();
    expect(h1?.classList.contains('hero-title-2xl')).toBeTruthy();
  });

  it(`渲染 ${QUICK_PROMPTS.length} 个 prompt 卡片`, () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const cards = container.querySelectorAll('.prompt-card');
    expect(cards.length).toBe(QUICK_PROMPTS.length);
  });

  it('prompt 卡片位于横向 .prompt-row 容器内', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const row = container.querySelector('.prompt-row');
    expect(row).not.toBeNull();
    expect(row?.querySelectorAll('.prompt-card').length).toBe(QUICK_PROMPTS.length);
  });

  it('点 prompt 卡片 → 调 onInsertPrompt(prompt text)', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const first = container.querySelector('.prompt-card') as HTMLElement;
    first.click();
    expect(baseProps.onInsertPrompt).toHaveBeenCalledWith(QUICK_PROMPTS[0]!.prompt);
  });

  it('不再渲染任务状态卡(.status-card)或 eyebrow', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    expect(container.querySelector('.status-card')).toBeNull();
    expect(container.querySelector('.eyebrow')).toBeNull();
  });

  it('不再自带 textarea 或发送按钮(统一由底部 Composer 处理)', () => {
    const { container } = render(<EmptyState {...baseProps} />);
    const ta = container.querySelector('textarea.empty-state-composer');
    expect(ta).toBeNull();
    const sendBtn = container.querySelector('button.empty-state-send');
    expect(sendBtn).toBeNull();
  });
});
