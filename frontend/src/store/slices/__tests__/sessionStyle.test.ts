/**
 * sessionStyles reducer 单测 — Round 6.1 Task 7。
 *
 * 验证:
 * - setSessionStyle 写入 sessionStyles[sid]
 * - 改一个 sid 不影响其它 sid 的 style
 * - 对不存在的 sid 写入是合法操作(plan 偏差:首次切风格时
 *   sessions list 可能还没 load,允许创建 key 以便 ws send / PATCH
 *   后端能读到 style;后端 PATCH 会校验 session 存在,前端传 stale id
 *   自然 4xx)。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../../index';

describe('sessionStyles', () => {
  beforeEach(() => {
    // 每个用例前重置持久化字段
    useStore.setState({ sessionStyles: {} });
  });

  it('setSessionStyle 写入 store', () => {
    useStore.getState().setSessionStyle('s1', 'professional');
    expect(useStore.getState().sessionStyles['s1']).toBe('professional');
  });

  it('不影响其它 session 的 style', () => {
    useStore.setState({ sessionStyles: { s1: 'default', s2: 'concise' } });
    useStore.getState().setSessionStyle('s1', 'professional');
    const styles = useStore.getState().sessionStyles;
    expect(styles['s1']).toBe('professional');
    expect(styles['s2']).toBe('concise');
  });

  it('不存在的 sessionId 写入合法(首次切风格允许创建 key),不抛', () => {
    expect(() =>
      useStore.getState().setSessionStyle('nonexistent', 'concise')
    ).not.toThrow();
    expect(useStore.getState().sessionStyles['nonexistent']).toBe('concise');
  });
});
