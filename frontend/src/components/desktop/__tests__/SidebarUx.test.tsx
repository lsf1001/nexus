/**
 * Sidebar UX 增量测试 — 2026-07-23 第十轮(4 项修复锁测)。
 *
 * 现有 Sidebar.test.tsx 已用过时 props (`onViewChange / wechatConnected /
 * wechatInboxCount`),继续 fail 不在本任务修复范围。本文件**只**测 4 项
 * 新行为,跟当前 SidebarProps 对齐(不含过时 props)。
 *
 * 覆盖:
 *   1. 删除二次确认:× → "确定?" + "取消";确定触发 onDeleteConversation;
 *      取消不触发。
 *   2. 重命名:双击 title → 编辑态(input 出现);Enter 调
 *      onRenameConversation(id, newTitle);Esc 取消。
 *   3. 星标排序:starred 的会话排在非 starred 前(组内仍按 updatedAt)。
 *   4. 搜索命中消息内容:title 不含但 messages[0].content 含 → 仍出现。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { Sidebar } from '../Sidebar';
import { useStore } from '../../../store';
import type { Conversation } from '../../../types';

function makeConv(
  id: string,
  title: string,
  options: { messages?: Conversation['messages']; updatedAt?: string } = {},
): Conversation {
  return {
    id,
    title,
    createdAt: new Date(options.updatedAt ?? '2026-07-23T00:00:00Z'),
    updatedAt: options.updatedAt ?? '2026-07-23T00:00:00Z',
    messages: options.messages ?? [],
    channel: undefined,
  };
}

interface Harness {
  onSelectConversation: ReturnType<typeof vi.fn>;
  onDeleteConversation: ReturnType<typeof vi.fn>;
  onRenameConversation: ReturnType<typeof vi.fn>;
  onNewTask: ReturnType<typeof vi.fn>;
  onOpenPreferences?: ReturnType<typeof vi.fn>;
}

function makeHarness(overrides: Partial<Harness> = {}): Harness {
  return {
    onSelectConversation: vi.fn(),
    onDeleteConversation: vi.fn(),
    onRenameConversation: vi.fn(),
    onNewTask: vi.fn(),
    onOpenPreferences: vi.fn(),
    ...overrides,
  };
}

describe('Sidebar UX 第十轮(删除确认 / 重命名 / 星标分组 / 消息搜索)', () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it('点 × → 进入确认态(出现"确定?"和"取消");点取消 → 不删', () => {
    const conv = makeConv('1', '测试对话');
    const h = makeHarness();
    const { container } = render(
      <Sidebar
        conversations={[conv]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    const delBtn = container.querySelector('button.delete-btn') as HTMLButtonElement;
    expect(delBtn).not.toBeNull();
    fireEvent.click(delBtn);

    expect(h.onDeleteConversation).not.toHaveBeenCalled();

    const confirmBtn = container.querySelector('button.delete-confirm') as HTMLButtonElement;
    const cancelBtn = container.querySelector('button.delete-cancel') as HTMLButtonElement;
    expect(confirmBtn).not.toBeNull();
    expect(cancelBtn).not.toBeNull();
    expect(container.querySelector('button.delete-btn')).toBeNull();

    fireEvent.click(cancelBtn);
    expect(h.onDeleteConversation).not.toHaveBeenCalled();

    // 回到初始态(只有一个 ×)
    expect(container.querySelector('button.delete-btn')).not.toBeNull();
    expect(container.querySelector('button.delete-confirm')).toBeNull();
  });

  it('点 × → "确定?" → onDeleteConversation(id) 调一次', () => {
    const conv = makeConv('42', '要被删的对话');
    const h = makeHarness();
    const { container } = render(
      <Sidebar
        conversations={[conv]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    fireEvent.click(container.querySelector('button.delete-btn') as HTMLButtonElement);
    fireEvent.click(container.querySelector('button.delete-confirm') as HTMLButtonElement);

    expect(h.onDeleteConversation).toHaveBeenCalledTimes(1);
    expect(h.onDeleteConversation).toHaveBeenCalledWith('42');
  });

  it('双击 title → 进入编辑态(input 出现);Enter → onRenameConversation', () => {
    const conv = makeConv('7', '旧标题');
    const h = makeHarness();
    const { container } = render(
      <Sidebar
        conversations={[conv]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    // 初始:无 input
    expect(container.querySelector('.rename-input')).toBeNull();

    const titleEl = container.querySelector('.task-item-body') as HTMLElement;
    fireEvent.doubleClick(titleEl);

    const input = container.querySelector('.rename-input') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.value).toBe('旧标题');

    fireEvent.change(input, { target: { value: '新标题' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(h.onRenameConversation).toHaveBeenCalledWith('7', '新标题');
    expect(h.onSelectConversation).not.toHaveBeenCalled();
  });

  it('编辑态按 Esc → 取消(不调 onRenameConversation)', () => {
    const conv = makeConv('8', '旧');
    const h = makeHarness();
    const { container } = render(
      <Sidebar
        conversations={[conv]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    fireEvent.doubleClick(container.querySelector('.task-item-body') as HTMLElement);
    const input = container.querySelector('.rename-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '改一半' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    expect(h.onRenameConversation).not.toHaveBeenCalled();
    // 退出编辑态
    expect(container.querySelector('.rename-input')).toBeNull();
  });

  it('星标会话排在非星标之前(prop 顺序反着传也以 starredIds 为准)', () => {
    // 故意让旧 updatedAt 的 starred 排前
    const starred = makeConv('s', '星标会话', { updatedAt: '2026-01-01T00:00:00Z' });
    const fresh = makeConv('f', '最新会话', { updatedAt: '2026-07-23T00:00:00Z' });
    const h = makeHarness();
    useStore.setState({ starredIds: ['s'] });
    const { container } = render(
      <Sidebar
        // prop 顺序:fresh 在前(后挂的)但被 star 后应排到 s 之后
        conversations={[fresh, starred]}
        currentConversationId={null}
        onSelectConversation={h.onSelectConversation}
        onDeleteConversation={h.onDeleteConversation}
        onRenameConversation={h.onRenameConversation}
        onNewTask={h.onNewTask}
        onOpenPreferences={h.onOpenPreferences}
      />,
    );

    const items = Array.from(container.querySelectorAll('.task-item'));
    expect(items.length).toBe(2);
    expect(items[0]!.textContent).toContain('星标会话');
    expect(items[1]!.textContent).toContain('最新会话');
  });

  it('搜索匹配 messages[].content(title 不命中也命中)', () => {
    const convA = makeConv('1', '普通对话', {
      messages: [
        { id: 'm1', role: 'user', content: '我想聊一下 Kubernetes 部署', createdAt: new Date() },
      ],
    });
    const convB = makeConv('2', '另一对话', {
      messages: [{ id: 'm2', role: 'user', content: '今天天气真好', createdAt: new Date() }],
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

    const items = container.querySelectorAll('.task-item');
    expect(items.length).toBe(1);
    expect(container.textContent).toContain('普通对话');
    expect(container.textContent).not.toContain('另一对话');
  });
});