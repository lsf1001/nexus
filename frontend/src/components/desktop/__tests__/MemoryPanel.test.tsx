/**
 * MemoryPanel 单测 — #14 记忆面板增强(2026-07-23)。
 *
 * 锁 4 条契约:
 *   1. 渲染路径/字节/行数
 *   2. 复制路径按钮 → 调 clipboard.writeText(memory.path)
 *   3. 复制内容按钮 → 调 clipboard.writeText(memory.content)
 *   4. 刷新按钮 → 调 fetchMemory + loading 期间 disabled
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { MemoryPanel } from '../MemoryPanel';
import { useStore } from '../../../store';
import { useToastStore } from '../../../store/useToast';

const sampleMemory = {
  exists: true,
  path: '/Users/test/.nexus/AGENTS.md',
  content: '# Long-term memory\n\n- User prefers dark mode\n',
  bytes: 42,
  lines: 3,
};

describe('MemoryPanel (#14 增强)', () => {
  beforeEach(() => {
    useStore.setState({
      memory: sampleMemory,
      memoryLoading: false,
      memoryError: null,
    });
    // jsdom 无 clipboard API,显式 mock
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
      writable: true,
    });
    vi.restoreAllMocks();
  });

  afterEach(() => {
    useToastStore.getState().clear();
    vi.restoreAllMocks();
  });

  it('渲染路径 / 字节 / 行数', () => {
    const { container } = render(<MemoryPanel />);
    expect(container.textContent).toContain('AGENTS.md');
    expect(container.textContent).toContain('42 B');
    expect(container.textContent).toContain('3 行');
  });

  it('点"复制路径" → 调 clipboard.writeText(path) + toast', async () => {
    const writeSpy = navigator.clipboard.writeText as ReturnType<typeof vi.fn>;
    const pushSpy = vi.spyOn(useToastStore.getState(), 'push');
    const { container } = render(<MemoryPanel />);
    const btn = container.querySelector('[data-testid="memory-copy-path"]') as HTMLButtonElement;
    fireEvent.click(btn);
    await waitFor(() => {
      expect(writeSpy).toHaveBeenCalledWith(sampleMemory.path);
    });
    expect(pushSpy).toHaveBeenCalledWith('info', '路径已复制', 1500);
  });

  it('点"复制内容" → 调 clipboard.writeText(content) + toast', async () => {
    const writeSpy = navigator.clipboard.writeText as ReturnType<typeof vi.fn>;
    const pushSpy = vi.spyOn(useToastStore.getState(), 'push');
    const { container } = render(<MemoryPanel />);
    const btn = container.querySelector('[data-testid="memory-copy-content"]') as HTMLButtonElement;
    fireEvent.click(btn);
    await waitFor(() => {
      expect(writeSpy).toHaveBeenCalledWith(sampleMemory.content);
    });
    expect(pushSpy).toHaveBeenCalledWith('info', '内容已复制', 1500);
  });

  it('点"下载" → 触发 anchor click + toast', () => {
    const pushSpy = vi.spyOn(useToastStore.getState(), 'push');
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    const { container } = render(<MemoryPanel />);
    const btn = container.querySelector('[data-testid="memory-download"]') as HTMLButtonElement;
    fireEvent.click(btn);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(pushSpy).toHaveBeenCalledWith('info', '已下载 AGENTS.md', 1500);
  });

  it('点"刷新" → 调 fetchMemory + 期间按钮 disabled', async () => {
    // 让 fetchMemory 挂起 → 期间按钮 disabled
    let resolveFetch: (() => void) | null = null;
    const fetchSpy = vi
      .spyOn(useStore.getState(), 'fetchMemory')
      .mockImplementation(
        () =>
          new Promise<void>((resolve) => {
            resolveFetch = resolve;
          }),
      );
    const { container } = render(<MemoryPanel />);
    const btn = container.querySelector('[data-testid="memory-refresh"]') as HTMLButtonElement;
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn.disabled).toBe(true);
    });
    expect(btn.textContent).toContain('刷新中');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    // 完成后按钮恢复
    if (resolveFetch) resolveFetch();
    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    });
    expect(btn.textContent).toContain('刷新');
  });

  it('空状态(!exists) → 渲染提示文案,不渲染 action 区', () => {
    useStore.setState({
      memory: { ...sampleMemory, exists: false, content: '' },
      memoryLoading: false,
      memoryError: null,
    });
    const { container } = render(<MemoryPanel />);
    expect(container.textContent).toContain('还没有长期记忆');
    expect(container.querySelector('[data-testid="memory-refresh"]')).toBeNull();
  });
});