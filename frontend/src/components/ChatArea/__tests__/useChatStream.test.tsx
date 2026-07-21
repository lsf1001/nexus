/**
 * useChatStream 单测 — streamingPaused gate(2026-07-13 stop 按钮改造,
 * 2026-07-20 重构:gate 从 useChatStream 内部 stoppedRef 升级为 store.streamingPaused,
 * handler 直接读 store,appendToAssistant / ensureAssistantPlaceholder 从本 hook 移除)。
 *
 * 覆盖 4 个核心场景:
 *   1. markUserStopped() 后,store.appendAssistantPatch 不再写 store
 *   2. pushUserAndPlaceholder 会清 streamingPaused gate,新一轮流正常写入
 *   3. reset() 也会清 gate(配合 resetTrigger / 新会话)
 *   4. markUserStopped 之前 appendAssistantPatch 正常写入(regression 不退化)
 *
 * 为什么单测而不是 e2e:streamingPaused 是 store 状态,组件外可观察,e2e
 * 也能验证,但单测更精准(直接断言 store action 写入次数)。
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
    // 重置 store.messages + gate
    useStore.getState().setConversationMessages([]);
    useStore.setState({ streamingPaused: false });
  });

  it('markUserStopped 后 store.appendAssistantPatch 不写 store', () => {
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
    expect(useStore.getState().streamingPaused).toBe(true);

    // 直接调 store action(模拟 handleChunk 收到帧)
    act(() => {
      useStore.getState().appendAssistantPatch({ content: 'late chunk' });
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
      useStore.getState().appendAssistantPatch({ content: 'should not write' });
    });
    expect(useStore.getState().conversationMessages[1]?.content).toBe('');

    // 新一轮 user → pushUserAndPlaceholder 应清 gate
    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('second'));
    });
    expect(useStore.getState().streamingPaused).toBe(false);
    act(() => {
      useStore.getState().appendAssistantPatch({ content: 'new chunk' });
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
    expect(useStore.getState().streamingPaused).toBe(false);
    // 模拟新一轮 — push user + appendAssistantPatch
    act(() => {
      result.current.pushUserAndPlaceholder(makeUser('after reset'));
    });
    act(() => {
      useStore.getState().appendAssistantPatch({ content: 'ok' });
    });
    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('ok');
  });

  it('未 markUserStopped 时 store.appendAssistantPatch 正常写入(regression)', () => {
    // 不走 useChatStream — 直接用 store 模拟:先 push user+placeholder,
    // 然后调 store.appendAssistantPatch(等价 handler 调 path)
    useStore.getState().setConversationMessages([
      makeUser('hi'),
      {
        id: 'placeholder',
        role: 'assistant',
        content: '',
        createdAt: new Date(),
      },
    ]);
    act(() => {
      useStore.getState().appendAssistantPatch({ content: 'chunk1' });
    });
    act(() => {
      useStore.getState().appendAssistantPatch({ content: ' chunk2' });
    });
    act(() => {
      useStore.getState().appendAssistantPatch({ thinking: 'thinking...' });
    });

    const msgs = useStore.getState().conversationMessages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1]?.content).toBe('chunk1 chunk2');
    expect(msgs[1]?.thinking).toBe('thinking...');
  });
});