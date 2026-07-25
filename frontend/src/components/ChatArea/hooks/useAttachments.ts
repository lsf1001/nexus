/**
 * Composer 本地附件 state hook(第十三轮,2026-07-24)。
 *
 * 职责:
 *   - 维护 LocalAttachment[] 列表(图片预览 + 文件名 + 上传状态)
 *   - addFiles → 立即 push pending;异步 POST /api/attachments;成功后回填 serverId
 *   - remove(id) → 列表移除;若已 uploaded 调 DELETE /api/attachments/{id}
 *   - clear()    → 全清 + 全 DELETE
 *
 * 不做:
 *   - 上传到 store:附件不上 Zustand,只在 hook 内,组件卸载就丢(用户已发送则成功)
 *   - 进度条:20MB 以内本地直传够快,无进度条需求
 *   - retry:失败 toast 用户手动重传;不静默重试
 */
import { useCallback, useState } from 'react'
import { useToastStore } from '@/store/useToast'

const MAX_FILE_SIZE = 20 * 1024 * 1024
const ALLOWED_MIME_PREFIXES = ['image/', 'text/']
const ALLOWED_MIME_EXACT = new Set([
  'application/pdf',
  'application/json',
])

interface AttachmentMetadata {
  id: string
  project_id: string
  original_name: string
  stored_filename: string
  file_path: string
  mime: string
  size: number
  uploaded_at: string
}

export interface LocalAttachment {
  id: string // client uuid
  file: File
  previewUrl?: string
  originalName: string
  mime: string
  size: number
  uploadStatus: 'pending' | 'uploading' | 'uploaded' | 'failed'
  serverId?: string
  error?: string
}

const isAllowedMime = (mime: string): boolean =>
  ALLOWED_MIME_PREFIXES.some((p) => mime.startsWith(p)) ||
  ALLOWED_MIME_EXACT.has(mime)

const clientUuid = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `c_${Math.random().toString(36).slice(2)}_${Date.now()}`

const toastError = (msg: string): void => {
  // 直接调 store 不用 selector 订阅,避免 upload 流程触发额外重渲染
  useToastStore.getState().push('error', msg, 5000)
}

export interface UseAttachmentsReturn {
  attachments: LocalAttachment[]
  addFiles: (files: File[]) => void
  remove: (id: string) => void
  clear: () => void
  /** 已上传的 server id 列表(给 ChatArea 提交时拼到 message) */
  uploadedServerIds: () => string[]
}

export function useAttachments(projectId: string): UseAttachmentsReturn {
  const [attachments, setAttachments] = useState<LocalAttachment[]>([])

  const uploadOne = useCallback(
    async (att: LocalAttachment): Promise<void> => {
      setAttachments((prev) =>
        prev.map((a) =>
          a.id === att.id ? { ...a, uploadStatus: 'uploading' as const } : a,
        ),
      )
      const form = new FormData()
      form.append('file', att.file, att.originalName)
      form.append('project_id', projectId)
      try {
        const res = await fetch('/api/attachments', {
          method: 'POST',
          body: form,
        })
        if (!res.ok) {
          const msg =
            res.status === 413
              ? `文件过大 (>20MB): ${att.originalName}`
              : res.status === 415
                ? `不支持的附件类型: ${att.originalName}`
                : `上传失败: ${att.originalName}`
          setAttachments((prev) =>
            prev.map((a) =>
              a.id === att.id
                ? { ...a, uploadStatus: 'failed' as const, error: msg }
                : a,
            ),
          )
          toastError(msg)
          return
        }
        const meta = (await res.json()) as AttachmentMetadata
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === att.id
              ? { ...a, uploadStatus: 'uploaded' as const, serverId: meta.id }
              : a,
          ),
        )
      } catch {
        const msg = `上传失败: ${att.originalName}`
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === att.id
              ? { ...a, uploadStatus: 'failed' as const, error: msg }
              : a,
          ),
        )
        toastError(msg)
      }
    },
    [projectId],
  )

  const addFiles = useCallback(
    (files: File[]) => {
      const newOnes: LocalAttachment[] = []
      for (const file of files) {
        if (file.size > MAX_FILE_SIZE) {
          toastError(`文件过大 (>20MB): ${file.name}`)
          continue
        }
        if (!isAllowedMime(file.type)) {
          toastError(`不支持的附件类型: ${file.name}`)
          continue
        }
        const id = clientUuid()
        const previewUrl = file.type.startsWith('image/')
          ? URL.createObjectURL(file)
          : undefined
        newOnes.push({
          id,
          file,
          previewUrl,
          originalName: file.name,
          mime: file.type,
          size: file.size,
          uploadStatus: 'pending',
        })
      }
      if (newOnes.length === 0) return
      setAttachments((prev) => [...prev, ...newOnes])
      // 立即开始上传
      for (const att of newOnes) {
        void uploadOne(att)
      }
    },
    [uploadOne],
  )

  const remove = useCallback(
    (id: string) => {
      const target = attachments.find((a) => a.id === id)
      if (!target) return
      setAttachments((prev) => prev.filter((a) => a.id !== id))
      // 卸载时 revoke previewUrl;若已 uploaded 则调 DELETE
      if (target.previewUrl) URL.revokeObjectURL(target.previewUrl)
      if (target.serverId) {
        void fetch(`/api/attachments/${target.serverId}`, {
          method: 'DELETE',
        }).catch(() => {
          /* 静默:删不删无所谓 */
        })
      }
    },
    [attachments],
  )

  const clear = useCallback(() => {
    // 卸载所有 previewUrl + 异步 DELETE 所有 uploaded(读当前 attachments)
    for (const a of attachments) {
      if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
      if (a.serverId) {
        void fetch(`/api/attachments/${a.serverId}`, {
          method: 'DELETE',
        }).catch(() => {})
      }
    }
    setAttachments([])
  }, [attachments])

  const uploadedServerIds = useCallback(
    () =>
      attachments
        .filter((a) => a.uploadStatus === 'uploaded' && a.serverId)
        .map((a) => a.serverId!),
    [attachments],
  )

  return { attachments, addFiles, remove, clear, uploadedServerIds }
}
