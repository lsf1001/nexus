/**
 * useDraft 单测 — 第十一轮(2026-07-23)Composer 草稿持久化。
 *
 * WHY:hook 是 ChatArea 内的逻辑抽离,行为固定(读草稿 / 写草稿 / 清草稿)
 * 后适合 vitest 单测覆盖。三个核心场景:
 *   1. 输入文字 + 500ms 防抖 → localStorage.setItem('nexus-draft', ...) 被调
 *   2. 挂载时 conversationId 为空 → 读草稿填回 input + toast
 *   3. send 成功 → clearDraft() → localStorage.removeItem
 *
 * jsdom 注:vitest 默认 localStorage 不可用("ExperimentalWarning: localStorage
 * is not available"),用 vi.stubGlobal 或 mockStorage 设全局 polyfill。
 * 这里手写一个简版 mockStorage,只暴露 getItem / setItem / removeItem。
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useDraft } from '../hooks/useDraft';
import { useToastStore } from '../../../store/useToast';

const DRAFT_KEY = 'nexus-draft';

interface MockStorage {
  data: Map<string, string>;
  getItem: (k: string) => string | null;
  setItem: (k: string, v: string) => void;
  removeItem: (k: string) => void;
}

function makeMockStorage(): MockStorage {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k)! : null),
    setItem: (k, v) => data.set(k, v),
    removeItem: (k) => data.delete(k),
  };
}

describe('useDraft (第十一轮 Composer 草稿)', () => {
  let store: MockStorage;
  let originalLocalStorage: Storage | undefined;
  let originalGetItem: typeof Storage.prototype.getItem | undefined;

  beforeEach(() => {
    store = makeMockStorage();
    // jsdom 默认暴露 localStorage 但 vi 报警告;显式替换为 mock
    originalLocalStorage = globalThis.localStorage;
    originalGetItem = Storage.prototype.getItem;
    Object.defineProperty(window, 'localStorage', {
      value: store,
      configurable: true,
      writable: true,
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
    if (originalGetItem) {
      Storage.prototype.getItem = originalGetItem;
    }
    vi.useRealTimers();
    useToastStore.getState().clear();
  });

  it('saveDraftEffect(500ms 后)→ localStorage.setItem("nexus-draft", JSON)', () => {
    const { result } = renderHook(() => useDraft());
    // 调 saveDraftEffect("hello")
    act(() => {
      result.current.saveDraftEffect('hello');
    });
    // 500ms 未到 → 还没写
    expect(store.data.has(DRAFT_KEY)).toBe(false);
    // 推进 500ms
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(true);
    const raw = store.data.get(DRAFT_KEY)!;
    expect(JSON.parse(raw).text).toBe('hello');
    expect(typeof JSON.parse(raw).savedAt).toBe('number');
  });

  it('saveDraftEffect("") → removeItem (而不是 setItem 空字符串)', () => {
    const { result } = renderHook(() => useDraft());
    store.data.set(DRAFT_KEY, JSON.stringify({ text: 'old', savedAt: 0 }));
    act(() => {
      result.current.saveDraftEffect('');
      vi.advanceTimersByTime(500);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
  });

  it('loadOnMount(conversationId=null) → 读草稿 + setInput + toast', () => {
    store.data.set(
      DRAFT_KEY,
      JSON.stringify({ text: 'restored text', savedAt: Date.now() - 60_000 }),
    );
    const setInput = vi.fn();
    const pushSpy = vi.spyOn(useToastStore.getState(), 'push');
    const { result } = renderHook(() => useDraft());
    act(() => {
      result.current.loadOnMount(null, setInput);
    });
    expect(setInput).toHaveBeenCalledWith('restored text');
    // 读出后立即清掉(避免 reload 又恢复)
    expect(store.data.has(DRAFT_KEY)).toBe(false);
    // toast
    expect(pushSpy).toHaveBeenCalledWith('info', expect.stringContaining('已恢复草稿'), 3500);
  });

  it('loadOnMount(conversationId=有) → 不读草稿', () => {
    store.data.set(DRAFT_KEY, JSON.stringify({ text: 'should not read', savedAt: 0 }));
    const setInput = vi.fn();
    const { result } = renderHook(() => useDraft());
    act(() => {
      result.current.loadOnMount('conv-1', setInput);
    });
    expect(setInput).not.toHaveBeenCalled();
    // key 留着,没动
    expect(store.data.has(DRAFT_KEY)).toBe(true);
  });

  it('loadOnMount 只跑一次(第二次调是 noop)', () => {
    store.data.set(DRAFT_KEY, JSON.stringify({ text: 'first', savedAt: 0 }));
    const setInput = vi.fn();
    const { result } = renderHook(() => useDraft());
    act(() => {
      result.current.loadOnMount(null, setInput);
    });
    expect(setInput).toHaveBeenCalledTimes(1);
    // 第二次:store 里没了 / 但即使有也不应该再读
    store.data.set(DRAFT_KEY, JSON.stringify({ text: 'second', savedAt: 0 }));
    act(() => {
      result.current.loadOnMount(null, setInput);
    });
    expect(setInput).toHaveBeenCalledTimes(1);
  });

  it('clearDraft → 立即清 localStorage', () => {
    store.data.set(DRAFT_KEY, JSON.stringify({ text: 'x', savedAt: 0 }));
    const { result } = renderHook(() => useDraft());
    act(() => {
      result.current.clearDraft();
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
  });

  it('saveDraftEffect 后续 change → cleanup 取消前一次 setTimeout(防抖)', () => {
    const { result } = renderHook(() => useDraft());
    act(() => {
      result.current.saveDraftEffect('a');
    });
    act(() => {
      vi.advanceTimersByTime(300);
      // 300ms 时再 saveDraftEffect('ab') → 取消前一次
      result.current.saveDraftEffect('ab');
      vi.advanceTimersByTime(300); // 距离 'ab' 只走了 300ms,不够 500
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
    // 再推进 200ms → 'ab' 满 500ms
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(true);
    expect(JSON.parse(store.data.get(DRAFT_KEY)!).text).toBe('ab');
  });

  it('loadOnMount 触发的 setInput 不会立即覆盖回 localStorage(skipNextSave)', () => {
    // 先放一个草稿
    store.data.set(
      DRAFT_KEY,
      JSON.stringify({ text: 'restored', savedAt: Date.now() - 30_000 }),
    );
    const setInput = vi.fn((v: string) => {
      // 模拟 React:setInput 触发 input state 变化 → 父组件 useEffect → saveDraftEffect
      result.current.saveDraftEffect(v);
    });
    const { result } = renderHook(() => useDraft());
    // 模拟"父组件 mount:loadOnMount 跑 → setInput → 触发 input state → 触发 saveDraftEffect"
    act(() => {
      result.current.loadOnMount(null, setInput);
    });
    // 500ms 后不应该写 localStorage(loadOnMount 标记 skipNextSave)
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
  });

  // 第十一轮-2(2026-07-23):切会话路径覆盖。
  // WHY:ChatArea resetTrigger effect 内显式调 clearDraft,必须保证它
  // 是"立即 + 取消 pending 防抖"的语义,而不是依赖 500ms 防抖写空串。
  // 否则"用户在 500ms 防抖窗口内切会话 → 空 input 触发 saveDraftEffect('') →
  // 500ms 后 removeDraft" 会清掉刚刚写下的草稿。
  it('clearDraft 立即清 localStorage 并取消 pending timer', () => {
    const { result } = renderHook(() => useDraft());
    // 1) 模拟用户输入到一半 — 触发了 saveDraftEffect 但 timer 未到
    act(() => {
      result.current.saveDraftEffect('half written');
    });
    // 200ms 后还没到 500ms 防抖 → localStorage 还空
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
    // 2) 这时切会话(模拟 resetTrigger effect 调 clearDraft)
    act(() => {
      result.current.clearDraft();
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
    // 3) 再推进 500ms → 原 pending timer 被清掉,不会写 localStorage
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
  });

  it('clearDraft 之后,saveDraftEffect("") 不再生效(timer 已 cancel)', () => {
    const { result } = renderHook(() => useDraft());
    store.data.set(DRAFT_KEY, JSON.stringify({ text: 'stale', savedAt: 0 }));
    act(() => {
      result.current.clearDraft();
    });
    // 清完后:即便父组件又触发一次 saveDraftEffect(''),也不该写空串
    act(() => {
      result.current.saveDraftEffect('');
      vi.advanceTimersByTime(500);
    });
    expect(store.data.has(DRAFT_KEY)).toBe(false);
  });
});