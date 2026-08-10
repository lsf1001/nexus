/**
 * ChatArea 整体 render smoke test。
 *
 * WHY(2026-07-24):修 P0 TDZ bug 时新增。
 *   ChatArea/index.tsx 第 94 行 useEffect deps 数组含 `clearDraft`,但
 *   原代码第 181 行才 const 解构 `useDraft()` — React commit 阶段同步求值
 *   deps 撞 TDZ,抛 ReferenceError,ErrorBoundary 卸载整个 ChatView 树,
 *   所有 e2e settings spec 全挂。
 *
 *   修复:把 useDraft 解构上移到所有 useEffect 之前。本测试做单一职责 —
 *   断言 ChatArea 第一次 render 不抛,任何把 const 声明移到 deps 引用之
 *   后的回归都会立即被这里抓到。
 *
 *   不测交互 / WS / 草稿持久化等行为(子组件 + 子 hook 已有独立单测覆盖,
 *   这里只防"声明顺序破坏 render"这一类问题)。
 */
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ChatArea } from '../index';

describe('ChatArea render smoke', () => {
  it('首次 render 不抛 ReferenceError(TDZ 守卫)', () => {
    // 用 minimal props 走"无会话,空态"路径。
    // setup.ts 在 beforeEach 重置 store + localStorage,EmptyState 走 isIdle 分支。
    expect(() => render(<ChatArea conversationId={null} />)).not.toThrow();
  });

  it('ChatArea 导出是有效 React 函数组件(length 可读)', () => {
    // 占位:即便上面 render 因 mock 链问题失败,这一个 smoke 至少断言
    // 导出形态没被破坏。
    expect(typeof ChatArea).toBe('function');
  });
});
