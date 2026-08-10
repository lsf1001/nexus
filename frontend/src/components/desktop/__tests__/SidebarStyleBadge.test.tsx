/**
 * Sidebar 风格徽标测试 — Round 6.1 Task 10。
 *
 * 覆盖:
 * 1. sessionStyles[id] = 'default' → 不显示徽标
 * 2. sessionStyles[id] = 'concise' → 显示 "简洁" 灰底徽标
 * 3. sessionStyles[id] = 'professional' → 显示 "专业" 紫底徽标
 * 4. sessionStyles[id] = undefined → 不显示(跟 default 等价)
 *
 * WHY:数据来源走 store.sessionStyles 而非 DB / Conversation.style 字段。
 *  - loadSessions 在 useConversationCrud 里把后端 sessions.style seed 到
 *    store(Round 6.1 Task 7 决定的唯一入口);
 *  - 风格切换走 store.setSessionStyle + PATCH,失败回滚到 prevStyle;
 *  - 因此 Sidebar 列表项读取 store 是唯一同步准确的入口;
 *  - DB 拉取慢且需要 round-trip,store 已经把 sessionStyles 持久化到
 *    localStorage(走 uiPrefs slice 的 partialize),首屏 rehydrate 后
 *    即可读。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { Sidebar } from '../Sidebar';
import { useStore } from '../../../store';
import type { Conversation } from '../../../types';

function makeConv(id: string, title: string, updatedAt = '2026-08-06T00:00:00Z'): Conversation {
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
  onSelectConversation: () => {},
  onDeleteConversation: () => {},
  onRenameConversation: () => {},
  onNewTask: () => {},
  onOpenPreferences: () => {},
};

describe('Sidebar 风格徽标(Round 6.1 Task 10)', () => {
  beforeEach(() => {
    // 每个用例独立重置 sessionStyles,防止污染。
    useStore.setState({ sessionStyles: {} });
  });

  it('default 风格不显示徽标', () => {
    const conv = makeConv('s1', '默认风格对话');
    useStore.setState({ sessionStyles: { s1: 'default' } });
    const { container } = render(<Sidebar {...baseProps} conversations={[conv]} currentConversationId={null} />);
    expect(container.querySelector('[data-style]')).toBeNull();
    expect(container.textContent).not.toContain('简洁');
    expect(container.textContent).not.toContain('专业');
  });

  it('undefined 风格不显示徽标(等同于 default)', () => {
    const conv = makeConv('s1', '未设置风格');
    // store 留空,等同于 undefined
    const { container } = render(<Sidebar {...baseProps} conversations={[conv]} currentConversationId={null} />);
    expect(container.querySelector('[data-style]')).toBeNull();
  });

  it('concise 显示简洁徽标(带 data-style="concise")', () => {
    const conv = makeConv('s1', '简洁对话');
    useStore.setState({ sessionStyles: { s1: 'concise' } });
    const { container } = render(<Sidebar {...baseProps} conversations={[conv]} currentConversationId={null} />);
    const badge = container.querySelector('[data-style="concise"]');
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe('简洁');
  });

  it('professional 显示专业徽标(带 data-style="professional")', () => {
    const conv = makeConv('s1', '专业对话');
    useStore.setState({ sessionStyles: { s1: 'professional' } });
    const { container } = render(<Sidebar {...baseProps} conversations={[conv]} currentConversationId={null} />);
    const badge = container.querySelector('[data-style="professional"]');
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe('专业');
  });
});
