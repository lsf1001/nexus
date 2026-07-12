/**
 * useChatSend 单测 — 验证 6 类行为:
 * - (1) 空 / 纯空白内容不发送
 * - (2) WS 未连接 → setLastError(ws_not_open) 并 return(不调 send / pushUser)
 * - (3) readyState !== OPEN 同样阻止发送(鬼影消息防线)
 * - (4) 正常发送推 user + 占位 + 拼 WSMessage(无 session_id 时 title<=30 字)
 * - (5) 旧会话走 session_id,新会话走 title(分支 2 选 1)
 * - (6) send message 后清理 input + setLastError(null) + setIsLoading(true) + armWatchdog
 * - (7) refs 改变时 callback 引用更新(useCallback dep 行为)
 *
 * 注:hook 入口的所有副作用都通过 args 注入,便于隔离测试。
 */
import { describe, expect, it, vi, type Mock } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useChatSend, type UseChatSendArgs } from '../hooks/useChatSend'
import type { WSMessage, Message } from '../../../types'

function makeArgs(overrides: Partial<UseChatSendArgs> = {}): {
  args: UseChatSendArgs
  spies: {
    send: Mock
    setIsLoading: Mock
    setLastError: Mock
    clearInput: Mock
    armWatchdog: Mock
    pushUserAndPlaceholder: Mock
  }
} {
  const spies = {
    send: vi.fn(),
    setIsLoading: vi.fn(),
    setLastError: vi.fn(),
    clearInput: vi.fn(),
    armWatchdog: vi.fn(),
    pushUserAndPlaceholder: vi.fn(),
  }
  const args: UseChatSendArgs = {
    wsConnected: true,
    getReadyState: () => 1 /* WebSocket.OPEN */,
    getSessionId: () => 'session-existing',
    send: spies.send,
    setIsLoading: spies.setIsLoading,
    setLastError: spies.setLastError,
    clearInput: spies.clearInput,
    armWatchdog: spies.armWatchdog,
    pushUserAndPlaceholder: spies.pushUserAndPlaceholder,
    ...overrides,
  }
  return { args, spies }
}

describe('useChatSend', () => {
  it('空 / 纯空白内容不发送', () => {
    const { args, spies } = makeArgs()
    const { result } = renderHook(() => useChatSend(args))
    result.current('')
    result.current('   ')
    expect(spies.send).not.toHaveBeenCalled()
    expect(spies.pushUserAndPlaceholder).not.toHaveBeenCalled()
    expect(spies.setIsLoading).not.toHaveBeenCalled()
  })

  it('WS 未连接 → setLastError(ws_not_open) 并 return,不发任何副作用', () => {
    const { args, spies } = makeArgs({ wsConnected: false })
    const { result } = renderHook(() => useChatSend(args))
    result.current('hello')
    expect(spies.setLastError).toHaveBeenCalledTimes(1)
    const errArg = spies.setLastError.mock.calls[0]?.[0] as { code: string; retryable: boolean }
    expect(errArg.code).toBe('ws_not_open')
    expect(errArg.retryable).toBe(true)
    expect(spies.send).not.toHaveBeenCalled()
    expect(spies.pushUserAndPlaceholder).not.toHaveBeenCalled()
  })

  it('readyState !== OPEN(CLOSING/CLOSED) → 同样阻止发送', () => {
    // wsConnected: true 但底层 socket 已断 → 必须再过一次 readyState 闸门
    const { args, spies } = makeArgs({
      wsConnected: true,
      getReadyState: () => 3 /* WebSocket.CLOSED */,
    })
    const { result } = renderHook(() => useChatSend(args))
    result.current('hello')
    expect((spies.setLastError.mock.calls[0]?.[0] as { code: string }).code).toBe('ws_not_open')
    expect(spies.send).not.toHaveBeenCalled()
  })

  it('正常发送:旧会话走 session_id', () => {
    const { args, spies } = makeArgs({
      getSessionId: () => 'sid-abc',
    })
    const { result } = renderHook(() => useChatSend(args))
    result.current('hello world')
    // 调用顺序:setIsLoading(true) → armWatchdog → setLastError(null) → clearInput → pushUserAndPlaceholder → send
    expect(spies.setIsLoading).toHaveBeenCalledWith(true)
    expect(spies.armWatchdog).toHaveBeenCalledTimes(1)
    expect(spies.setLastError).toHaveBeenCalledWith(null)
    expect(spies.clearInput).toHaveBeenCalledTimes(1)
    expect(spies.pushUserAndPlaceholder).toHaveBeenCalledTimes(1)
    const userMsg = spies.pushUserAndPlaceholder.mock.calls[0]?.[0] as Message
    expect(userMsg.role).toBe('user')
    expect(userMsg.content).toBe('hello world')
    expect(userMsg.id).toBeTypeOf('string')
    expect(userMsg.createdAt).toBeInstanceOf(Date)
    // send 收到 WSMessage 带 session_id 没 title
    expect(spies.send).toHaveBeenCalledTimes(1)
    const wsMsg = spies.send.mock.calls[0]?.[0] as WSMessage
    expect(wsMsg.content).toBe('hello world')
    expect(wsMsg.session_id).toBe('sid-abc')
    expect(wsMsg.title).toBeUndefined()
  })

  it('新会话(getSessionId=null)→ 走 title<=30 字', () => {
    const { args, spies } = makeArgs({ getSessionId: () => null })
    const { result } = renderHook(() => useChatSend(args))
    const long = 'a'.repeat(50) + ' suffix'
    result.current(long)
    expect(spies.send).toHaveBeenCalledTimes(1)
    const wsMsg = spies.send.mock.calls[0]?.[0] as WSMessage
    expect(wsMsg.title).toBe('a'.repeat(30))
    expect(wsMsg.session_id).toBeUndefined()
  })

  it('args 中任一依赖变化 → 返回的 send 引用更新(useCallback dep)', () => {
    // 模拟上层 props 改变(用户切换会话 / wsConnected 变化)
    const first = makeArgs({ wsConnected: true })
    const second = makeArgs({ wsConnected: true })
    const { result, rerender } = renderHook(
      ({ args }: { args: UseChatSendArgs }) => useChatSend(args),
      { initialProps: { args: first.args } },
    )
    const sendRefA = result.current
    rerender({ args: second.args })
    const sendRefB = result.current
    expect(sendRefA).not.toBe(sendRefB)
  })

  it('args 不变 → send 引用保持稳定(useCallback cache 命中)', () => {
    const { args } = makeArgs()
    const { result, rerender } = renderHook(() => useChatSend(args))
    const a = result.current
    rerender()
    expect(result.current).toBe(a)
  })

  it('内容被 trim 再发送(空格前缀不被走 send)', () => {
    const { args, spies } = makeArgs()
    const { result } = renderHook(() => useChatSend(args))
    result.current('   hello   ')
    expect((spies.send.mock.calls[0]?.[0] as WSMessage).content).toBe('hello')
    expect((spies.pushUserAndPlaceholder.mock.calls[0]?.[0] as Message).content).toBe('hello')
  })
})
