/**
 * AttachmentBar — Composer 下方附件预览条(SPEC §4.2)。
 *
 * 形态:
 *   - 空数组 → 整条 hidden(浏览器默认 hidden 属性 + aria-hidden)
 *   - 每个 chip:缩略图(图片 / 首字母 placeholder) + body(name + size) + ×
 *
 * 交互:
 *   - × 按钮 → onRemove(id)
 *   - 状态后缀:pending='排队中…' / uploading='上传中…' / failed='失败'
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { AttachmentBar } from '../AttachmentBar'
import type { LocalAttachment } from '../hooks/useAttachments'

const mockAttachment = (overrides: Partial<LocalAttachment> = {}): LocalAttachment => ({
  id: 'a1',
  file: new File([new Uint8Array(10)], 'note.txt', { type: 'text/plain' }),
  originalName: 'note.txt',
  mime: 'text/plain',
  size: 10,
  uploadStatus: 'uploaded',
  ...overrides,
})

describe('AttachmentBar', () => {
  it('空数组时整条隐藏', () => {
    const { container } = render(<AttachmentBar attachments={[]} onRemove={() => {}} />)
    expect(container.firstChild).toHaveAttribute('hidden')
  })

  it('显示文件名 + 大小', () => {
    render(
      <AttachmentBar
        attachments={[mockAttachment({ originalName: 'spec.pdf', size: 245123 })]}
        onRemove={() => {}}
      />,
    )
    expect(screen.getByText('spec.pdf')).toBeInTheDocument()
    expect(screen.getByText(/239 KB|240 KB|240KB|239KB/)).toBeInTheDocument()
  })

  it('点 × 触发 onRemove(id)', () => {
    const onRemove = vi.fn()
    render(
      <AttachmentBar
        attachments={[mockAttachment({ id: 'a1' })]}
        onRemove={onRemove}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '移除附件' }))
    expect(onRemove).toHaveBeenCalledWith('a1')
  })

  it('uploading 状态显示 spinner 后缀', () => {
    render(
      <AttachmentBar
        attachments={[mockAttachment({ uploadStatus: 'uploading' })]}
        onRemove={() => {}}
      />,
    )
    expect(screen.getByText(/上传中/)).toBeInTheDocument()
  })
})