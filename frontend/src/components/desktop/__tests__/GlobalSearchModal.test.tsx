/**
 * GlobalSearchModal 测试 — Round 3 Task 3.4。
 *
 * 契约:
 *   - 输入触发 fetch,debounce 后显示结果
 *   - snippet 含 <mark> HTML 通过 dangerouslySetInnerHTML 渲染
 *   - 点结果调 onSelect(sessionId)
 *   - Esc 调 onClose
 *   - 空结果显示"无匹配"
 *   - 按 role(user/assistant)显示 badge
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GlobalSearchModal } from '../GlobalSearchModal';
import { searchMessages } from '../../../lib/api';
import { useGlobalSearchStore } from '../store/useGlobalSearchStore';

vi.mock('../../../lib/api', () => ({
  searchMessages: vi.fn(),
}));

const baseProps = {
  open: true,
  onClose: vi.fn(),
  onSelect: vi.fn(),
};

function mockResults(rows: Array<{
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  snippet: string;
  created_at: string;
}>): { results: typeof rows; count: number } {
  return { results: rows, count: rows.length };
}

describe('GlobalSearchModal(⌘F 全局搜索面板)', () => {
  beforeEach(() => {
    baseProps.onClose.mockClear();
    baseProps.onSelect.mockClear();
    vi.mocked(searchMessages).mockReset();
    useGlobalSearchStore.setState({ isOpen: false });
  });

  it('open=true 时渲染搜索 input + 自动聚焦', async () => {
    vi.mocked(searchMessages).mockResolvedValue(mockResults([]));
    const { container } = render(<GlobalSearchModal {...baseProps} />);
    const input = screen.getByPlaceholderText(/搜索消息/) as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(container.querySelector('.global-search-modal')).not.toBeNull();
    await waitFor(() => expect(input).toHaveFocus(), { timeout: 200 });
  });

  it('open=false 时不渲染', () => {
    vi.mocked(searchMessages).mockResolvedValue(mockResults([]));
    const { container } = render(<GlobalSearchModal {...baseProps} open={false} />);
    expect(container.querySelector('.global-search-modal')).toBeNull();
  });

  it('输入触发 fetch,debounce 后显示结果 + <mark> HTML 正确渲染', async () => {
    vi.mocked(searchMessages).mockResolvedValue(
      mockResults([
        {
          session_id: 's1',
          role: 'user',
          content: '原始内容',
          snippet: '这是 <mark>关键词</mark> 上下文',
          created_at: '2026-08-01T10:00:00Z',
        },
      ]),
    );

    render(<GlobalSearchModal {...baseProps} />);
    const input = screen.getByPlaceholderText(/搜索消息/) as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { value: '关键词' } });
    });
    // debounce 200ms
    await waitFor(
      () => {
        expect(searchMessages).toHaveBeenCalledWith('关键词', 50);
      },
      { timeout: 1000 },
    );
    await waitFor(() => {
      // snippet 通过 dangerouslySetInnerHTML 注入 → <mark> 真的渲染成元素
      const mark = document.querySelector('.global-search-snippet mark');
      expect(mark).not.toBeNull();
      expect(mark?.textContent).toBe('关键词');
    });
  });

  it('点结果 → 调 onSelect(sessionId) 并关弹窗', async () => {
    vi.mocked(searchMessages).mockResolvedValue(
      mockResults([
        {
          session_id: 's-target',
          role: 'assistant',
          content: 'reply',
          snippet: 'reply <mark>foo</mark>',
          created_at: '2026-08-01T10:00:00Z',
        },
      ]),
    );
    const { container } = render(<GlobalSearchModal {...baseProps} />);
    const input = screen.getByPlaceholderText(/搜索消息/) as HTMLInputElement;

    await act(async () => {
      fireEvent.change(input, { target: { value: 'foo' } });
    });
    await waitFor(() => {
      const item = container.querySelector('.global-search-item');
      expect(item).not.toBeNull();
    });
    const item = container.querySelector('.global-search-item') as HTMLElement;
    fireEvent.click(item);
    expect(baseProps.onSelect).toHaveBeenCalledWith('s-target');
    expect(baseProps.onClose).toHaveBeenCalled();
  });

  it('Esc 调 onClose', async () => {
    vi.mocked(searchMessages).mockResolvedValue(mockResults([]));
    render(<GlobalSearchModal {...baseProps} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(baseProps.onClose).toHaveBeenCalled();
  });

  it('点 overlay 调 onClose', async () => {
    vi.mocked(searchMessages).mockResolvedValue(mockResults([]));
    const { container } = render(<GlobalSearchModal {...baseProps} />);
    const overlay = container.querySelector('.command-palette-overlay');
    expect(overlay).not.toBeNull();
    fireEvent.click(overlay as HTMLElement);
    expect(baseProps.onClose).toHaveBeenCalled();
  });

  it('空结果显示"无匹配"', async () => {
    vi.mocked(searchMessages).mockResolvedValue(mockResults([]));
    render(<GlobalSearchModal {...baseProps} />);
    const input = screen.getByPlaceholderText(/搜索消息/) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: 'nothing' } });
    });
    await waitFor(() => {
      expect(screen.getByText(/无匹配/)).toBeInTheDocument();
    });
  });

  it('结果按 role 显示 user / assistant badge', async () => {
    vi.mocked(searchMessages).mockResolvedValue(
      mockResults([
        {
          session_id: 's1',
          role: 'user',
          content: 'q',
          snippet: 'q <mark>x</mark>',
          created_at: '2026-08-01T10:00:00Z',
        },
        {
          session_id: 's2',
          role: 'assistant',
          content: 'a',
          snippet: 'a <mark>x</mark>',
          created_at: '2026-08-01T10:05:00Z',
        },
      ]),
    );
    render(<GlobalSearchModal {...baseProps} />);
    const input = screen.getByPlaceholderText(/搜索消息/) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: 'x' } });
    });
    await waitFor(() => {
      expect(document.querySelectorAll('.global-search-badge.user').length).toBe(1);
      expect(document.querySelectorAll('.global-search-badge.assistant').length).toBe(1);
    });
  });

  it('searchMessages 失败 → 静默,显示空态', async () => {
    vi.mocked(searchMessages).mockRejectedValue(new Error('boom'));
    render(<GlobalSearchModal {...baseProps} />);
    const input = screen.getByPlaceholderText(/搜索消息/) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { value: 'fail' } });
    });
    await waitFor(() => {
      expect(screen.getByText(/无匹配/)).toBeInTheDocument();
    });
  });
});