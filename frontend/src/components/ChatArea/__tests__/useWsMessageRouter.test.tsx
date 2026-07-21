/**
 * useWsMessageRouter 派发表单测 — 验证 dispatcher 正确把 frame 路由到
 * wsHandlers.ts 里的具体 handler,以及 ctx 变化时 callback 引用更新。
 *
 * 覆盖 6 类路径(等价于 node:test 覆盖,但用 vitest + RTL 走 React hook):
 * - (1) 未知 frame type 时 noop(不抛错,不调用 ctx 里任何方法)
 * - (2) thinking 帧 → store.appendAssistantPatch 写 thinking
 * - (3) chunk 帧 → store.appendAssistantPatch 写 content
 * - (4) error 帧 → setLastError
 * - (5) confirmation_request 帧 → setPendingConfirmation(event_id/actions)
 * - (6) ctx 引用变化 → 返回的 dispatcher 引用更新(useCallback dep 行为)
 * - (7) null / 非对象 / 缺 type 字段 → 不抛错,吞掉
 *
 * 2026-07-20:handler 不再走 ctx.stream,直接用 useStore.getState().appendAssistantPatch,
 * 所以本测试 spy store action(spy 整个 store getState 返回值),不再 spy stream。
 */
import { describe, expect, it, vi, beforeEach, type Mock } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useWsMessageRouter } from '../hooks/useWsMessageRouter'
import type { WsRouterCtx } from '../hooks/wsHandlers'
import { useStore } from '../../../store'
import type { ConfirmationAction } from '../../../types'

function makeCtx(spies?: { appendAssistantPatch: Mock }): {
  ctx: WsRouterCtx
  spies: {
    appendAssistantPatch: Mock
    setLastError: Mock
    setIsLoading: Mock
    setPendingClarification: Mock
    setPendingConfirmation: Mock
    disarmWatchdog: Mock
  }
} {
  const appendAssistantPatch = spies?.appendAssistantPatch ?? vi.fn()
  // 用一个真实 store action 替换,spy 它
  const realAppend = useStore.getState().appendAssistantPatch
  useStore.setState({ appendAssistantPatch: appendAssistantPatch as typeof realAppend })

  const setLastError = vi.fn()
  const setIsLoading = vi.fn()
  const setPendingClarification = vi.fn()
  const setPendingConfirmation = vi.fn()
  const disarmWatchdog = vi.fn()
  const ctx: WsRouterCtx = {
    setLastError,
    setIsLoading,
    setPendingClarification,
    setPendingConfirmation,
    disarmWatchdog,
  }
  return {
    ctx,
    spies: {
      appendAssistantPatch,
      setLastError,
      setIsLoading,
      setPendingClarification,
      setPendingConfirmation,
      disarmWatchdog,
    },
  }
}

describe('useWsMessageRouter', () => {
  beforeEach(() => {
    // 还原 store action(防止前一个 case 残留 spy)
    useStore.setState({ conversationMessages: [], streamingPaused: false })
  })

  it('未知 type 字段 → noop,不抛错', () => {
    const { ctx } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    // 不在 HANDLERS 表的 type — hook 默认吞掉
    expect(() => result.current({ type: 'totally_unknown' })).not.toThrow()
  })

  it('null / 非对象 / 缺 type 字段 → 静默忽略', () => {
    const { ctx } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    // 3 种 malformed 输入都不应走到 ctx 任何方法
    result.current(null)
    result.current(undefined)
    result.current('string-not-object')
    result.current({ noTypeField: 1 })
    // 因为 frame 没 type,narrowing 直接 return,不会调任何 handler
  })

  it('thinking 帧 → store.appendAssistantPatch 写 thinking + disarmWatchdog + setIsLoading(false)', () => {
    const { ctx, spies } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    result.current({ type: 'thinking', content: 'hmm let me think' })
    expect(spies.appendAssistantPatch).toHaveBeenCalledWith({ thinking: 'hmm let me think' })
    expect(spies.setIsLoading).toHaveBeenCalledWith(false)
    expect(spies.disarmWatchdog).toHaveBeenCalledTimes(1)
  })

  it('chunk 帧 → store.appendAssistantPatch 写 content + 清 LastError + disarmWatchdog', () => {
    const { ctx, spies } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    result.current({ type: 'chunk', content: 'hello ' })
    expect(spies.appendAssistantPatch).toHaveBeenCalledWith({ content: 'hello ' })
    // chunk 帧到时清 lastError(老 error 帧被覆盖)
    expect(spies.setLastError).toHaveBeenCalledWith(null)
    expect(spies.disarmWatchdog).toHaveBeenCalledTimes(1)
  })

  it('error 帧 → setLastError 写 message/retryable/code + disarmWatchdog', () => {
    const { ctx, spies } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    result.current({
      type: 'error',
      content: 'model overloaded',
      retryable: true,
      error_code: 'rate_limit',
    })
    expect(spies.setLastError).toHaveBeenCalledTimes(1)
    const errArg = spies.setLastError.mock.calls[0]?.[0] as { message: string; retryable: boolean; code: string; at: number }
    expect(errArg.message).toBe('model overloaded')
    expect(errArg.retryable).toBe(true)
    expect(errArg.code).toBe('rate_limit')
    expect(errArg.at).toBeTypeOf('number')
    expect(spies.disarmWatchdog).toHaveBeenCalledTimes(1)
  })

  it('confirmation_request 帧(actions 齐全)→ setPendingConfirmation(interrupt_id / event_id / actions)', () => {
    const { ctx, spies } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    const actions: ConfirmationAction[] = [
      {
        tool_name: 'edit_file',
        target_path: '~ / AGENTS.md',
        preview: 'append line',
        description: '写用户偏好',
        options: [{ label: '允许', decision: 'approve' }, { label: '拒绝', decision: 'reject' }],
      },
    ]
    result.current({
      type: 'confirmation_request',
      interrupt_id: 'int-1',
      event_id: 42,
      actions,
    })
    expect(spies.setPendingConfirmation).toHaveBeenCalledTimes(1)
    expect(spies.setPendingConfirmation).toHaveBeenCalledWith({
      interruptId: 'int-1',
      eventId: 42,
      actions,
    })
  })

  it('ctx 引用变化 → 返回的 dispatcher 引用更新(useCallback dep)', () => {
    // 第一份 ctx 与第二份 ctx 不同实例 — 同 hook rerender 时 useCallback dep
    // 改变 → 返回新函数引用(useWsConnection 拿到引用后判断该不该重连)
    const { ctx: ctxA } = makeCtx()
    const { ctx: ctxB } = makeCtx()

    const { result, rerender } = renderHook(
      ({ ctx }: { ctx: WsRouterCtx }) => useWsMessageRouter(ctx),
      { initialProps: { ctx: ctxA } },
    )
    const dispatchA = result.current
    rerender({ ctx: ctxB })
    const dispatchB = result.current
    expect(dispatchA).not.toBe(dispatchB)
  })

  it('ctx 引用不变 → 返回的 dispatcher 引用保持(useCallback 缓存命中)', () => {
    const { ctx } = makeCtx()
    const { result, rerender } = renderHook(() => useWsMessageRouter(ctx))
    const first = result.current
    rerender()
    expect(result.current).toBe(first)
  })
})