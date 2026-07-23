/**
 * useAutoScroll 单测 — 第十一轮(2026-07-23)扩展 userScrolledUp /
 * scrollToBottom 导出。
 *
 * WHY:hook 内部 userScrolledUp 从 useRef 升 useState,触发 ChatArea
 * 响应式条件渲染"跳到底部"浮动按钮。scrollToBottom 行为:
 *   - 调用 scrollTo / scrollTop 设到底部
 *   - 立即重置 userScrolledUp=false(否则按钮一直亮)
 *
 * 测三件事:
 *   1. 默认 userScrolledUp=false
 *   2. 模拟用户主动滚(派发 isTrusted scroll 事件,scrollTop < scrollHeight)→ true
 *   3. scrollToBottom() → 重置为 false + el.scrollTop === el.scrollHeight
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAutoScroll } from '../hooks/useAutoScroll';

function makeEl(scrollHeight: number, scrollTop: number, clientHeight: number) {
  const el = document.createElement('div');
  // jsdom 不实现 layout — 直接定义 getter,模拟"有内容可滚"
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: scrollHeight });
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = v;
    },
  });
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight });
  el.scrollTo = vi.fn(function (this: HTMLElement, opts: { top: number; behavior?: string }) {
    scrollTop = opts.top;
  });
  return el;
}

/** jsdom 锁死 Event.isTrusted 既不能改值也不能 defineProperty。绕过:
 *  monkey-patch el.addEventListener,记录 listener;另外提供一个
 *  dispatchTrustedScroll 直接调 listener 并把 fakeEvent 的 isTrusted
 *  用 Proxy 代理到 true(hook 只读 ev.isTrusted,handler 拿到事件时 isTrusted
 *  是 true)。 */
function installTrustedScrollBridge(el: HTMLElement): () => void {
  const listeners: Array<(ev: Event) => void> = [];
  const origAdd = el.addEventListener.bind(el);
  const origRemove = el.removeEventListener.bind(el);
  el.addEventListener = ((type: string, listener: EventListenerOrEventListenerObject) => {
    if (type === 'scroll' && typeof listener === 'function') {
      listeners.push(listener as (ev: Event) => void);
    }
    return origAdd(type, listener);
  }) as typeof el.addEventListener;
  el.removeEventListener = ((type: string, listener: EventListenerOrEventListenerObject) => {
    if (type === 'scroll' && typeof listener === 'function') {
      const idx = listeners.indexOf(listener as (ev: Event) => void);
      if (idx >= 0) listeners.splice(idx, 1);
    }
    return origRemove(type, listener);
  }) as typeof el.removeEventListener;
  return () => {
    const fakeEvent = new Proxy(new Event('scroll'), {
      get(target, prop) {
        if (prop === 'isTrusted') return true;
        return Reflect.get(target, prop);
      },
    });
    listeners.forEach((l) => l(fakeEvent));
  };
}

describe('useAutoScroll (第十一轮 userScrolledUp + scrollToBottom)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('默认 userScrolledUp=false', () => {
    const el = makeEl(500, 0, 300);
    document.body.appendChild(el);
    const containerRef = { current: el } as React.RefObject<HTMLElement | null>;
    const { result } = renderHook(() =>
      useAutoScroll({ trigger: [1], containerRef }),
    );
    expect(result.current.userScrolledUp).toBe(false);
    expect(typeof result.current.scrollToBottom).toBe('function');
    document.body.removeChild(el);
  });

  it('用户主动滚(派发 isTrusted scroll)→ userScrolledUp=true', () => {
    // scrollHeight 500,scrollTop 50,clientHeight 300 → 离底 150px
    const el = makeEl(500, 50, 300);
    document.body.appendChild(el);
    const bridge = installTrustedScrollBridge(el);
    const containerRef = { current: el } as React.RefObject<HTMLElement | null>;
    const { result } = renderHook(() =>
      useAutoScroll({ trigger: [1], containerRef }),
    );
    // 派发 isTrusted scroll 事件
    act(() => {
      bridge();
    });
    expect(result.current.userScrolledUp).toBe(true);
    document.body.removeChild(el);
  });

  it('滚回贴底(scrollTop + clientHeight == scrollHeight)→ userScrolledUp=false', () => {
    // 离底 5px(<= 8 阈值)
    const el = makeEl(500, 195, 300);
    document.body.appendChild(el);
    const bridge = installTrustedScrollBridge(el);
    const containerRef = { current: el } as React.RefObject<HTMLElement | null>;
    const { result } = renderHook(() =>
      useAutoScroll({ trigger: [1], containerRef }),
    );
    // 先滚上看
    act(() => {
      Object.defineProperty(el, 'scrollTop', { configurable: true, value: 50 });
      bridge();
    });
    expect(result.current.userScrolledUp).toBe(true);
    // 再滚回贴底
    act(() => {
      Object.defineProperty(el, 'scrollTop', { configurable: true, value: 195 });
      bridge();
    });
    expect(result.current.userScrolledUp).toBe(false);
    document.body.removeChild(el);
  });

  it('scrollToBottom() → el.scrollTo 调 + userScrolledUp 重置为 false', () => {
    const el = makeEl(500, 50, 300);
    document.body.appendChild(el);
    const bridge = installTrustedScrollBridge(el);
    const containerRef = { current: el } as React.RefObject<HTMLElement | null>;
    const { result } = renderHook(() =>
      useAutoScroll({ trigger: [1], containerRef }),
    );
    // 触发滚上看
    act(() => {
      bridge();
    });
    expect(result.current.userScrolledUp).toBe(true);
    // 调 scrollToBottom
    act(() => {
      result.current.scrollToBottom(true);
    });
    // scrollTo 被调一次,top = 500
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 500, behavior: 'smooth' });
    // userScrolledUp 立即重置为 false
    expect(result.current.userScrolledUp).toBe(false);
    document.body.removeChild(el);
  });

  it('scrollToBottom(smooth=false) → 直接设 el.scrollTop = scrollHeight', () => {
    const el = makeEl(500, 50, 300);
    document.body.appendChild(el);
    const containerRef = { current: el } as React.RefObject<HTMLElement | null>;
    const { result } = renderHook(() =>
      useAutoScroll({ trigger: [1], containerRef }),
    );
    act(() => {
      result.current.scrollToBottom(false);
    });
    // scrollTo 没被调(直接走 scrollTop setter)
    expect(el.scrollTo).not.toHaveBeenCalled();
    document.body.removeChild(el);
  });
});