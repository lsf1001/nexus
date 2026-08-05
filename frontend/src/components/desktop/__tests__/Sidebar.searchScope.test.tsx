/**
 * Sidebar 搜索作用域测试 — Round 3 Task 3.5。
 *
 * 契约:
 *   - 渲染 segmented control [标题|全部]
 *   - 标题模式:只匹配 title(原有逻辑,无网络调用)
 *   - 全部模式:调 /api/search/messages,把命中 session_id 提前 + 高亮标记
 *   - 切换 segmented control → 更新 store.searchScope
 *
 * 复用现有 SidebarUx.test.tsx 的 makeConv / makeHarness helper 模式。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { Sidebar } from '../Sidebar';
import { useStore } from '../../../store';
import { searchMessages } from '../../../lib/api';
import type { Conversation } from '../../../types';

vi.mock('../../../lib/api', () => ({
  searchMessages: vi.fn(),
}));

function makeConv(
  id: string,
  title: string,
  options: { messages?: Conversation['messages']; updatedAt?: string } = {},
): Conversation {
  return {
    id,
    title,
    createdAt: new Date(options.updatedAt ?? '2026-08-05T00:00:00Z'),
    updatedAt: options.updatedAt ?? '2026-08-05T00:00:00Z',
    messages: options.messages ?? [],
    channel: undefined,
  };
}

interface Harness {
  onSelectConversation: Mock<(conv: Conversation) => void>;
  onDeleteConversation: Mock<(id: string) => void>;
  onRenameConversation: Mock<(id: string, title: string) => void | Promise<void>>;
  onNewTask: Mock<() => void>;
  onOpenPreferences?: Mock<() => void>;
}

function makeHarness(overrides: Partial<Harness> = {}): Harness {
  return {
    onSelectConversation: vi.fn<(conv: Conversation) => void>(),
    onDeleteConversation: vi.fn<(id: string) => void>(),
    onRenameConversation: vi.fn<(id: string, title: string) => void | Promise<void>>(),
    onNewTask: vi.fn<() => void>(),
    onOpenPreferences: vi.fn<() => void>(),
    ...overrides,
  };
}

describe('Sidebar 搜索作用域(Round 3 Task 3.5 双层匹配)', () => {
  beforeEach(() => {
    useStore.setState({ starredIds: [], searchScope: 'title' });
    vi.mocked(searchMessages).mockReset();
  });

  it('渲染 segmented control [标题|全部] 切换 store.searchScope', () => {
    const h = makeHarness();
    const { container } = render(
      <Sidebar
        conversations={[]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );
    // segmented 容器
    const seg = container.querySelector('.sidebar-search-scope');
    expect(seg).not.toBeNull();
    const titleBtn = container.querySelector('[data-scope="title"]') as HTMLButtonElement;
    const allBtn = container.querySelector('[data-scope="all"]') as HTMLButtonElement;
    expect(titleBtn).not.toBeNull();
    expect(allBtn).not.toBeNull();
    expect(titleBtn.getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(allBtn);
    expect(useStore.getState().searchScope).toBe('all');
    expect(allBtn.getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(titleBtn);
    expect(useStore.getState().searchScope).toBe('title');
    expect(titleBtn.getAttribute('aria-pressed')).toBe('true');
  });

  it('标题模式:只匹配 title,不调 searchMessages,关键词在 messages[] 命中不算', () => {
    const convA = makeConv('1', '普通对话', {
      messages: [
        { id: 'm1', role: 'user', content: 'kubernetes 部署方案', createdAt: new Date() },
      ],
    });
    const convB = makeConv('2', '另一对话', {
      messages: [{ id: 'm2', role: 'user', content: 'k8s', createdAt: new Date() }],
    });
    const h = makeHarness();
    const { container } = render(
      <Sidebar
        conversations={[convA, convB]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'kubernetes' } });

    expect(container.querySelectorAll('.task-item').length).toBe(0);
    expect(searchMessages).not.toHaveBeenCalled();
  });

  it('全部模式:调 searchMessages,命中 session 提前 + 高亮标记', async () => {
    vi.mocked(searchMessages).mockResolvedValue({
      results: [
        {
          session_id: 's-hit',
          role: 'user',
          content: 'kubernetes 部署方案',
          snippet: '这是 <mark>kubernetes</mark> 上下文',
          created_at: '2026-08-05T10:00:00Z',
        },
      ],
      count: 1,
    });

    const convs = [
      makeConv('s-other', '无关对话'),
      makeConv('s-hit', '命中会话'),
    ];
    const h = makeHarness();
    useStore.setState({ searchScope: 'all' });
    const { container } = render(
      <Sidebar
        conversations={convs}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'kubernetes' } });

    await waitFor(() => {
      expect(searchMessages).toHaveBeenCalledWith('kubernetes', 50);
    });
    await waitFor(() => {
      const items = container.querySelectorAll('.task-item');
      expect(items.length).toBe(2);
      // 命中会话应排在前面
      expect(items[0]!.getAttribute('data-conversation-id')).toBe('s-hit');
      // 高亮标记通过 dangerouslySetInnerHTML 注入 → <mark> 真的渲染
      const mark = container.querySelector('.task-item .search-snippet mark');
      expect(mark).not.toBeNull();
      expect(mark?.textContent).toBe('kubernetes');
    });
  });
});