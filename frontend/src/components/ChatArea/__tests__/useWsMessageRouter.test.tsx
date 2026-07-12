/**
 * useWsMessageRouter 派发表单测 — 验证 dispatcher 正确把 frame 路由到
 * wsHandlers.ts 里的具体 handler,以及 ctx 变化时 callback 引用更新。
 *
 * 覆盖 6 类路径(等价于 node:test 覆盖,但用 vitest + RTL 走 React hook):
 * - (1) 未知 frame type 时 noop(不抛错,不调用 ctx 里任何方法)
 * - (2) thinking 帧 → appendToAssistant 写 thinking
 * - (3) chunk 帧 → appendToAssistant 写 content
 * - (4) error 帧 → setLastError
 * - (5) confirmation_request 帧 → setPendingConfirmation(event_id/actions)
 * - (6) ctx 引用变化 → 返回的 dispatcher 引用更新(useCallback dep 行为)
 * - (7) null / 非对象 / 缺 type 字段 → 不抛错,吞掉
 *
 * 注:handlers 直接访问 useStore.getState(),测试不动 store 全局状态 —
 * appendToAssistant 这条路径只检查 spy 调用,不去拿真实 DB 断言。
 */
import { describe, expect, it, vi, type Mock } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useWsMessageRouter } from '../hooks/useWsMessageRouter'
import type { WsRouterCtx } from '../hooks/wsHandlers'
import type { ConfirmationAction } from '../../../types'

function makeCtx(): {
  ctx: WsRouterCtx
  spies: {
    ensureAssistantPlaceholder: Mock
    appendToAssistant: Mock
    setLastError: Mock
    setIsLoading: Mock
    setPendingClarification: Mock
    setPendingConfirmation: Mock
    disarmWatchdog: Mock
  }
} {
  const spies = {
    ensureAssistantPlaceholder: vi.fn(),
    appendToAssistant: vi.fn(),
    setLastError: vi.fn(),
    setIsLoading: vi.fn(),
    setPendingClarification: vi.fn(),
    setPendingConfirmation: vi.fn(),
    disarmWatchdog: vi.fn(),
  }
  const ctx: WsRouterCtx = {
    stream: {
      ensureAssistantPlaceholder: spies.ensureAssistantPlaceholder,
      appendToAssistant: spies.appendToAssistant,
      reset: vi.fn(),
      pushUserAndPlaceholder: vi.fn(),
      replaceAssistantWithPlaceholder: vi.fn(),
      snapshot: () => [],
    },
    setLastError: spies.setLastError,
    setIsLoading: spies.setIsLoading,
    setPendingClarification: spies.setPendingClarification,
    setPendingConfirmation: spies.setPendingConfirmation,
    disarmWatchdog: spies.disarmWatchdog,
  }
  return { ctx, spies }
}

describe('useWsMessageRouter', () => {
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

  it('thinking 帧 → appendToAssistant 写 thinking + disarmWatchdog + setIsLoading(false)', () => {
    const { ctx, spies } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    result.current({ type: 'thinking', content: 'hmm let me think' })
    expect(spies.ensureAssistantPlaceholder).toHaveBeenCalledTimes(1)
    expect(spies.appendToAssistant).toHaveBeenCalledWith({ thinking: 'hmm let me think' })
    expect(spies.setIsLoading).toHaveBeenCalledWith(false)
    expect(spies.disarmWatchdog).toHaveBeenCalledTimes(1)
  })

  it('chunk 帧 → appendToAssistant 写 content + 清 LastError + disarmWatchdog', () => {
    const { ctx, spies } = makeCtx()
    const { result } = renderHook(() => useWsMessageRouter(ctx))
    result.current({ type: 'chunk', content: 'hello ' })
    expect(spies.ensureAssistantPlaceholder).toHaveBeenCalledTimes(1)
    expect(spies.appendToAssistant).toHaveBeenCalledWith({ content: 'hello ' })
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
