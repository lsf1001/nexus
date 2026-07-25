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

  it('点图片缩略图打开 dialog 并显示 previewUrl', () => {
    const previewUrl = 'blob:http://localhost/abc-123'
    render(
      <AttachmentBar
        attachments={[
          mockAttachment({
            id: 'img1',
            mime: 'image/png',
            originalName: 'shot.png',
            previewUrl,
          }),
        ]}
        onRemove={() => {}}
      />,
    )
    const thumb = screen.getByRole('button', { name: '查看 shot.png' })
    fireEvent.click(thumb)
    const dialog = document.querySelector('dialog.attachment-image-dialog')
    expect(dialog).not.toBeNull()
    expect(dialog?.querySelector('img')).toHaveAttribute('src', previewUrl)
  })

  it('failed 状态显示失败文案 + is-failed class', () => {
    const { container } = render(
      <AttachmentBar
        attachments={[mockAttachment({ uploadStatus: 'failed', originalName: 'bad.png' })]}
        onRemove={() => {}}
      />,
    )
    expect(screen.getByText(/失败/)).toBeInTheDocument()
    const chip = container.querySelector('.attachment-chip')
    expect(chip?.className).toContain('is-failed')
  })

  it('多附件下点第二个 × 触发 onRemove(第二个 id)', () => {
    const onRemove = vi.fn()
    render(
      <AttachmentBar
        attachments={[
          mockAttachment({ id: 'a1', originalName: 'first.txt' }),
          mockAttachment({ id: 'a2', originalName: 'second.txt' }),
        ]}
        onRemove={onRemove}
      />,
    )
    const removeButtons = screen.getAllByRole('button', { name: '移除附件' })
    fireEvent.click(removeButtons[1])
    expect(onRemove).toHaveBeenCalledWith('a2')
  })

  it('图片但无 previewUrl 时渲染 initials placeholder(不渲染 img)', () => {
    const { container } = render(
      <AttachmentBar
        attachments={[
          mockAttachment({
            id: 'img-no-prev',
            mime: 'image/png',
            originalName: 'phantom.png',
          }),
        ]}
        onRemove={() => {}}
      />,
    )
    const thumb = container.querySelector('.attachment-chip-thumb')
    expect(thumb?.querySelector('img')).toBeNull()
    expect(thumb?.querySelector('span')).not.toBeNull()
  })

  it('文件名 chip 设置 title 属性等于 originalName', () => {
    const longName = 'a-very-long-filename-that-will-overflow-chip.png'
    const { container } = render(
      <AttachmentBar
        attachments={[mockAttachment({ originalName: longName })]}
        onRemove={() => {}}
      />,
    )
    const chipName = container.querySelector('.attachment-chip-name')
    expect(chipName).toHaveAttribute('title', longName)
  })
})