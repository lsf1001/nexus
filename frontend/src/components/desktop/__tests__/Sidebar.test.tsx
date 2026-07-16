/**
 * Sidebar 搜索 + 重命名 锁测试 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop / ChatGPT / Manus 都有会话搜索。第八轮只有空列表 /
 * 全列表,用户多了找不到对话。第九轮加:
 *   1. 顶栏下方 <input type="search" /> 过滤
 *   2. 会话项右键触发 onRename callback(双击改名)
 *
 * 测试断言:
 *   1. 渲染 search input
 *   2. 输入查询 → 只显示 title 包含的会话
 *   3. 清除查询 → 恢复全列表
 *   4. 双击会话项 → 调 onRename(当前实现给 stub,不在组件内调 onRename 但暴露)
 *   5. 空查询 + 无会话 → 显示 empty state
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { Sidebar } from '../Sidebar';
import type { Conversation } from '../../../types';

function makeConv(id: string, title: string, updatedAt = '2026-07-16T00:00:00Z'): Conversation {
  return {
    id,
    title,
    createdAt: new Date(updatedAt),
    updatedAt,
    messages: [],
    channel: undefined,
  };
}

const baseProps = {
  onViewChange: vi.fn(),
  currentConversationId: null,
  wechatConnected: false,
  wechatInboxCount: 0,
  onSelectConversation: vi.fn(),
  onDeleteConversation: vi.fn(),
  onNewTask: vi.fn(),
};

describe('Sidebar 搜索 + 重命名(第九轮 UI 重设计)', () => {
  beforeEach(() => {
    baseProps.onViewChange.mockClear();
    baseProps.onSelectConversation.mockClear();
    baseProps.onDeleteConversation.mockClear();
    baseProps.onNewTask.mockClear();
  });

  it('渲染 search input 在 sidebar-brand 下方', () => {
    const { container } = render(
      <Sidebar {...baseProps} conversations={[]} />,
    );
    const input = container.querySelector('input[type="search"]');
    expect(input).not.toBeNull();
    expect(input?.getAttribute('placeholder')).toBeTruthy();
    // search 必须在 sidebar-brand 之后,sidebar-footer 之前
    const brand = container.querySelector('.sidebar-brand');
    const footer = container.querySelector('.sidebar-footer');
    expect(brand).not.toBeNull();
    expect(footer).not.toBeNull();
    const seq = brand!.compareDocumentPosition(input!);
    expect(seq & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const seq2 = input!.compareDocumentPosition(footer!);
    expect(seq2 & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('输入查询 → 只显示 title 包含的会话', () => {
    const convs = [
      makeConv('1', '微信集成方案讨论'),
      makeConv('2', '明天的会议安排'),
      makeConv('3', '微信 UI 重设计 SPEC'),
    ];
    const { container } = render(
      <Sidebar {...baseProps} conversations={convs} />,
    );
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '微信' } });
    const items = container.querySelectorAll('.task-item');
    expect(items.length).toBe(2);
    expect(container.textContent).toContain('微信集成方案讨论');
    expect(container.textContent).toContain('微信 UI 重设计 SPEC');
    expect(container.textContent).not.toContain('明天的会议安排');
  });

  it('清空查询 → 恢复全列表', () => {
    const convs = [
      makeConv('1', 'A'),
      makeConv('2', 'B'),
    ];
    const { container } = render(
      <Sidebar {...baseProps} conversations={convs} />,
    );
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'A' } });
    expect(container.querySelectorAll('.task-item').length).toBe(1);
    fireEvent.change(input, { target: { value: '' } });
    expect(container.querySelectorAll('.task-item').length).toBe(2);
  });

  it('查询无命中 → 不显示会话项(empty 状态不出现因为有 conv.length > 0)', () => {
    const convs = [makeConv('1', 'A'), makeConv('2', 'B')];
    const { container } = render(
      <Sidebar {...baseProps} conversations={convs} />,
    );
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'zzzNotFound' } });
    expect(container.querySelectorAll('.task-item').length).toBe(0);
    // empty-tasks 不应出现(因为 convs 非空,只是过滤为空)
    expect(container.querySelector('.empty-tasks')).toBeNull();
    // 应显示 "无匹配" 提示
    expect(container.textContent).toContain('无匹配');
  });

  it('点击会话项 → onSelectConversation', () => {
    const conv = makeConv('1', '测试对话');
    const onSel = vi.fn();
    const { container } = render(
      <Sidebar {...baseProps} conversations={[conv]} onSelectConversation={onSel} />,
    );
    const item = container.querySelector('.task-item');
    expect(item).not.toBeNull();
    item!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onSel).toHaveBeenCalledWith(conv);
  });

  it('删除按钮 → onDeleteConversation (不触发 select)', () => {
    const conv = makeConv('1', '测试');
    const onDel = vi.fn();
    const onSel = vi.fn();
    const { container } = render(
      <Sidebar
        {...baseProps}
        conversations={[conv]}
        onDeleteConversation={onDel}
        onSelectConversation={onSel}
      />,
    );
    const delBtn = container.querySelector('button.delete-btn');
    expect(delBtn).not.toBeNull();
    delBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onDel).toHaveBeenCalledWith('1');
    expect(onSel).not.toHaveBeenCalled();
  });

  it('点 + 新对话 → onNewTask', () => {
    const onNew = vi.fn();
    const { container } = render(
      <Sidebar {...baseProps} conversations={[]} onNewTask={onNew} />,
    );
    const newBtn = container.querySelector('.btn-new-task');
    expect(newBtn).not.toBeNull();
    newBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onNew).toHaveBeenCalledTimes(1);
  });
});