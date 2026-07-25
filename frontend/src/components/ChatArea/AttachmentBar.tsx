/**
 * Composer 下方附件预览条(SPEC §4.2)。
 *
 * 形态:
 *   - 空数组 → 整条 hidden
 *   - 每行 3 个 chip,溢出横向 scroll
 *   - chip:48px 高,左缩略图(图片用 previewUrl / 文件用首字母 placeholder),
 *          中 文件名 + 大小,右 × 按钮
 *
 * 交互:
 *   - × → onRemove(id)
 *   - chip 主体 → 图片全屏 dialog;非图片弹 tooltip
 */
import { useState } from 'react'
import type { LocalAttachment } from './hooks/useAttachments'

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const initials = (name: string): string => {
  const stem = name.replace(/\.[^.]+$/, '')
  return (stem[0] ?? '?').toUpperCase()
}

interface AttachmentBarProps {
  attachments: LocalAttachment[]
  onRemove: (id: string) => void
}

export function AttachmentBar({ attachments, onRemove }: AttachmentBarProps): JSX.Element | null {
  const [viewingImage, setViewingImage] = useState<string | null>(null)
  if (attachments.length === 0) {
    return <div data-testid="attachment-bar" hidden aria-hidden="true" />
  }
  return (
    <div data-testid="attachment-bar" className="attachment-bar">
      {attachments.map((att) => {
        const isImage = att.mime.startsWith('image/')
        return (
          <div
            key={att.id}
            className={`attachment-chip ${att.uploadStatus === 'failed' ? 'is-failed' : ''}`}
          >
            <button
              type="button"
              className="attachment-chip-thumb"
              onClick={() => isImage && att.previewUrl && setViewingImage(att.previewUrl)}
              aria-label={`查看 ${att.originalName}`}
            >
              {isImage && att.previewUrl ? (
                <img src={att.previewUrl} alt={att.originalName} />
              ) : (
                <span aria-hidden="true">{initials(att.originalName)}</span>
              )}
            </button>
            <div className="attachment-chip-body">
              <div className="attachment-chip-name" title={att.originalName}>
                {att.originalName}
              </div>
              <div className="attachment-chip-meta">
                {formatSize(att.size)}
                {att.uploadStatus === 'uploading' && ' · 上传中…'}
                {att.uploadStatus === 'pending' && ' · 排队中…'}
                {att.uploadStatus === 'failed' && ' · 失败'}
              </div>
            </div>
            <button
              type="button"
              className="attachment-chip-remove"
              onClick={() => onRemove(att.id)}
              aria-label="移除附件"
            >
              ×
            </button>
          </div>
        )
      })}
      {viewingImage && (
        <dialog
          open
          className="attachment-image-dialog"
          onClick={() => setViewingImage(null)}
        >
          <img src={viewingImage} alt="" />
        </dialog>
      )}
    </div>
  )
}