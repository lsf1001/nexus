/**
 * useAttachments — 本地附件 state + 上传 + 移除。
 *
 * 设计:
 *   - addFiles(file[])  → push LocalAttachment{uploadStatus: 'pending'}
 *   - 立即异步 upload → 成功回填 serverId + uploadStatus: 'uploaded'
 *   - remove(id)       → 移除条目;若已 uploaded 调 DELETE /api/attachments/{id}
 *   - clear()          → 移除全部 + DELETE 所有 uploaded
 *   - 卸载时:revoke 所有未释放的 image previewUrl(防 blob 泄漏)
 *
 * 异常路径覆盖:
 *   - fetch reject(网络错误) → status=failed + toast
 *   - fetch 返 500           → status=failed + toast
 */
import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useAttachments } from '../hooks/useAttachments'
import { useToastStore } from '@/store/useToast'

const fileFromBytes = (name: string, bytes: number, type: string): File =>
  new File([new Uint8Array(bytes)], name, { type })

describe('useAttachments', () => {
  it('addFiles 后 attachments 列表长度 = 1', async () => {
    const { result } = renderHook(() => useAttachments('default'))
    const f = fileFromBytes('note.txt', 5, 'text/plain')
    await act(async () => {
      result.current.addFiles([f])
    })
    expect(result.current.attachments).toHaveLength(1)
    expect(result.current.attachments[0]?.originalName).toBe('note.txt')
  })

  it('remove 后 attachments 列表清空', async () => {
    const { result } = renderHook(() => useAttachments('default'))
    const f = fileFromBytes('note.txt', 5, 'text/plain')
    await act(async () => {
      result.current.addFiles([f])
    })
    const id = result.current.attachments[0]?.id
    act(() => {
      result.current.remove(id!)
    })
    expect(result.current.attachments).toHaveLength(0)
  })

  it('已上传附件 remove 时调 DELETE', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    // mock POST 返 201 + server id
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: 'att_1',
          project_id: 'default',
          original_name: 'note.txt',
          stored_filename: 'att_1.txt',
          file_path: '/x',
          mime: 'text/plain',
          size: 5,
          uploaded_at: '2026-01-01',
        }),
        { status: 201 },
      ),
    )
    const { result } = renderHook(() => useAttachments('default'))
    await act(async () => {
      result.current.addFiles([fileFromBytes('note.txt', 5, 'text/plain')])
    })
    // 等上传完成
    await waitFor(() => {
      expect(result.current.attachments[0]?.uploadStatus).toBe('uploaded')
    })
    const id = result.current.attachments[0]?.id
    act(() => {
      result.current.remove(id!)
    })
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/attachments/'),
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
    fetchSpy.mockRestore()
  })

  it('超 20MB 抛 toast error', async () => {
    const { result } = renderHook(() => useAttachments('default'))
    const f = fileFromBytes('big.bin', 21 * 1024 * 1024, 'text/plain')
    await act(async () => {
      result.current.addFiles([f])
    })
    expect(result.current.attachments).toHaveLength(0)
    // 不支持 mime 同理
    const bad = fileFromBytes('x.exe', 10, 'application/x-msdownload')
    await act(async () => {
      result.current.addFiles([bad])
    })
    expect(result.current.attachments).toHaveLength(0)
  })

  it('添加 image 后卸载 hook → revoke previewUrl(防 blob 泄漏)', async () => {
    // 把 createObjectURL 桩成已知字符串，便于断言 revoke 被调到的参数
    const createSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:nx/p1')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    const { result, unmount } = renderHook(() => useAttachments('default'))
    await act(async () => {
      result.current.addFiles([fileFromBytes('pic.png', 10, 'image/png')])
    })
    expect(createSpy).toHaveBeenCalled()
    expect(result.current.attachments[0]?.previewUrl).toBe('blob:nx/p1')

    // 用户直接卸载，未调 remove —— 验证 cleanup 兜底 revoke
    unmount()

    expect(revokeSpy).toHaveBeenCalledWith('blob:nx/p1')

    createSpy.mockRestore()
    revokeSpy.mockRestore()
  })

  it('fetch reject 时附件标记为 failed + 调 toast error', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(
      new Error('network down'),
    )
    // mock 后续可能的 DELETE 调用(失败后 serverId 不存在,实际不会有,所以无后续 mock 需求)
    const pushSpy = vi.spyOn(useToastStore.getState(), 'push')

    const { result } = renderHook(() => useAttachments('default'))
    await act(async () => {
      result.current.addFiles([fileFromBytes('note.txt', 5, 'text/plain')])
    })
    await waitFor(() => {
      expect(result.current.attachments[0]?.uploadStatus).toBe('failed')
    })
    expect(result.current.attachments[0]?.error).toContain('note.txt')
    expect(pushSpy).toHaveBeenCalledWith(
      'error',
      expect.stringContaining('note.txt'),
      expect.any(Number),
    )
    fetchSpy.mockRestore()
    pushSpy.mockRestore()
  })

  it('fetch 返 500 时附件标记为 failed + 调 toast error', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('boom', { status: 500 }))
    const pushSpy = vi.spyOn(useToastStore.getState(), 'push')

    const { result } = renderHook(() => useAttachments('default'))
    await act(async () => {
      result.current.addFiles([fileFromBytes('note.txt', 5, 'text/plain')])
    })
    await waitFor(() => {
      expect(result.current.attachments[0]?.uploadStatus).toBe('failed')
    })
    expect(result.current.attachments[0]?.error).toContain('note.txt')
    expect(pushSpy).toHaveBeenCalledWith(
      'error',
      expect.stringContaining('note.txt'),
      expect.any(Number),
    )
    fetchSpy.mockRestore()
    pushSpy.mockRestore()
  })
})
