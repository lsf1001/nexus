/**
 * useDraftConflict — 监听 storage 事件,跨 tab 改同 project 草稿 → 调 onConflict。
 *
 * Round 2(2026-07-30,SPEC §4.6)多 tab 草稿同步:同 key 在另一 tab 被修改
 * → 给调用方 remoteText + remoteSavedAt,由 ChatArea 弹 toast(降级为 warn
 * 因为 useToast store 不支持 actions)。
 *
 * 三类 case:
 *   - 同 project key 的 storage event → 触发 onConflict,带 remoteText/remoteSavedAt
 *   - 不同 project key  → 忽略
 *   - unmount 移除 listener → 不再触发
 *
 * 注意:jsdom 下 StorageEvent 没有 `storageArea` / `oldValue` 等所有字段的
 * 默认值,所以测试只填关键字段;hook 实现对 storageArea 不做断言(原
 * 浏览器 spec 保证事件来自其他 tab 时 storageArea 存在,但兜底处理更稳)。
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useDraftConflict } from '../hooks/useDraftConflict'

describe('useDraftConflict', () => {
  it('同 project 草稿被另一 tab 修改 → 触发 onConflict 带 remoteText/remoteSavedAt', () => {
    const onConflict = vi.fn()
    renderHook(() =>
      useDraftConflict({
        projectId: 'default',
        onConflict,
      }),
    )
    // 模拟另一 tab 写入同 key(格式与 useDraft 一致:{text, savedAt})
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'nexus-draft-default',
          oldValue: JSON.stringify({ text: 'a', savedAt: 1 }),
          newValue: JSON.stringify({ text: 'b', savedAt: 999 }),
        }),
      )
    })
    expect(onConflict).toHaveBeenCalledTimes(1)
    expect(onConflict).toHaveBeenCalledWith({
      remoteText: 'b',
      remoteSavedAt: 999,
    })
  })

  it('不同 project 的 storage 事件忽略', () => {
    const onConflict = vi.fn()
    renderHook(() => useDraftConflict({ projectId: 'default', onConflict }))
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'nexus-draft-other',
          oldValue: JSON.stringify({ text: 'a', savedAt: 1 }),
          newValue: JSON.stringify({ text: 'b', savedAt: 999 }),
        }),
      )
    })
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('unmount 时移除 listener', () => {
    const onConflict = vi.fn()
    const { unmount } = renderHook(() =>
      useDraftConflict({ projectId: 'default', onConflict }),
    )
    unmount()
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'nexus-draft-default',
          oldValue: JSON.stringify({ text: 'a', savedAt: 1 }),
          newValue: JSON.stringify({ text: 'b', savedAt: 999 }),
        }),
      )
    })
    expect(onConflict).not.toHaveBeenCalled()
  })
})