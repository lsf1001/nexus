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
import { useCallback, useEffect, useRef, useState } from 'react'
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
  /**
   * 已创建但尚未 revoke 的 previewUrl 集合。
   * 闭包 attachments 在卸载时读到的是陈旧值，所以另起 ref 记号。
   * remove / clear 时同步从 ref 移除已 revoke 的 url，
   * 最终 useEffect cleanup 兜底 revoke 剩余的（用户直接卸载 Composer 而没 remove 的场景）。
   */
  const previewUrlsRef = useRef<Set<string>>(new Set())

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
      // 注册 previewUrl 到 ref 供 unmount cleanup 兜底 revoke
      for (const att of newOnes) {
        if (att.previewUrl) previewUrlsRef.current.add(att.previewUrl)
      }
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
      if (target.previewUrl) {
        URL.revokeObjectURL(target.previewUrl)
        // 从 ref 注销，避免 unmount cleanup 重复 revoke (revoke 一个已 revoke 的 url 是无害的
        // 但保持 ref 干净更利于断言)
        previewUrlsRef.current.delete(target.previewUrl)
      }
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
      if (a.previewUrl) {
        URL.revokeObjectURL(a.previewUrl)
        previewUrlsRef.current.delete(a.previewUrl)
      }
      if (a.serverId) {
        void fetch(`/api/attachments/${a.serverId}`, {
          method: 'DELETE',
        }).catch(() => {})
      }
    }
    setAttachments([])
  }, [attachments])

  // 卸载时 revoke 任何仍持有的 previewUrl —— 用户添加 image 后不点 remove 直接卸载
  // Composer 也不提交的场景，否则 blob URL 会泄漏到 GC。
  // 用 ref 而非闭包 attachments，因为 cleanup 读到的是 render 闭包的旧值，
  // 而 ref 始终持有 addFiles 时登记的最新 url 集合。
  useEffect(() => {
    // 局部拷贝一份 url 集合：cleanup 执行时 ref.current 仍指向原 Set，
    // 但若后续 React 复用该 ref 对象，snapshot 能确保 revoke 的是这次 effect 看到过的 url
    const urlsSnapshot = previewUrlsRef.current
    return () => {
      for (const url of urlsSnapshot) {
        URL.revokeObjectURL(url)
      }
      urlsSnapshot.clear()
    }
  }, [])

  const uploadedServerIds = useCallback(
    () =>
      attachments
        .filter((a) => a.uploadStatus === 'uploaded' && a.serverId)
        .map((a) => a.serverId!),
    [attachments],
  )

  return { attachments, addFiles, remove, clear, uploadedServerIds }
}
