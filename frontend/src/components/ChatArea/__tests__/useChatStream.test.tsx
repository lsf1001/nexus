/**
 * useChatStream 单测 — stoppedRef gate(2026-07-13 stop 按钮改造)
 *
 * 覆盖 4 个核心场景:
 *   1. markUserStopped() 后,appendToAssistant 不再写 store
 *   2. pushUserAndPlaceholder 会清 stopped gate,新一轮流正常写入
 *   3. reset() 也会清 gate(配合 resetTrigger / 新会话)
 *   4. markUserStopped 之前 appendToAssistant 正常写入(regression 不退化)
 *
 * 为什么单测而不是 e2e:stoppedRef 是 useChatStream 内部的 useRef,组件外不可见,
 * e2e 只能验证"是否还有文本冒出来",但区分不出"是 markUserStopped 没生效" vs
 * "store 写入了但 React 没渲染"。直接调 hook 验证 store 写入次数更精准。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useChatStream } from '../hooks/useChatStream';
import { useStore } from '../../../store';
import type { Message } from '../../../types';

function makeUser(content: string): Message {
  return {
    id: `user-${content}`,
    role: 'user',
    content,
    createdAt: new Date(),
  };
}

describe('useChatStream — markUserStopped gate', () => {
  beforeEach(() => {
    // 重置 store.messages
    useStore.getState().setConversationMessages([]);
  });

  it('markUserStopped 后 appendToAssistant 不写 store', () => {
    const { result } = renderHook(() => useChatStream());

    // 先放一条 user + 占位
    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('hi'));
    });
    expect(useStore.getState().conversationMessages).toHaveLength(2);

    // markUserStopped → gate
    act(() => {
      result.current.markUserStopped();
    });

    // appendToAssistant 应被 gate 掉,store 不变
    act(() => {
      result.current.appendToAssistant({ content: 'late chunk' });
    });
    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('');
  });

  it('pushUserAndPlaceholder 清 stopped gate,新流正常写入', () => {
    const { result } = renderHook(() => useChatStream());

    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('first'));
    });
    act(() => {
      result.current.markUserStopped();
    });
    act(() => {
      result.current.appendToAssistant({ content: 'should not write' });
    });
    expect(useStore.getState().conversationMessages[1]?.content).toBe('');

    // 新一轮 user → pushUserAndPlaceholder 应清 gate
    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('second'));
    });
    act(() => {
      result.current.appendToAssistant({ content: 'new chunk' });
    });
    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(4);
    expect(msgs[3]?.content).toBe('new chunk');
  });

  it('reset 清 stopped gate', () => {
    const { result } = renderHook(() => useChatStream());

    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('hi'));
    });
    act(() => {
      result.current.markUserStopped();
    });
    act(() => {
      result.current.reset();
    });
    // 模拟新一轮 — push user + appendToAssistant
    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('after reset'));
    });
    act(() => {
      result.current.appendToAssistant({ content: 'ok' });
    });
    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('ok');
  });

  it('未 markUserStopped 时 appendToAssistant 正常写入(regression)', () => {
    const { result } = renderHook(() => useChatStream());

    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('hi'));
    });
    act(() => {
      result.current.appendToAssistant({ content: 'chunk1' });
    });
    act(() => {
      result.current.appendToAssistant({ content: ' chunk2' });
    });
    act(() => {
      result.current.appendToAssistant({ thinking: 'thinking...' });
    });

    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('chunk1 chunk2');
    expect(msgs[1]?.thinking).toBe('thinking...');
  });
});