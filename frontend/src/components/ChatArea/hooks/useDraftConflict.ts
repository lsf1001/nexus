/**
 * 多 tab 草稿冲突检测 hook(Round 2,2026-07-30,SPEC §4.6)。
 *
 * 职责:监听 window 'storage' 事件(浏览器原生只在 **其他 tab** 触发,
 * 不在本 tab — 模拟 storage event 即可绕开此限制做测试)。
 *
 *   - 同 projectId 的 localStorage key 被另一 tab 写入新值(newValue !== oldValue)
 *     → 解析 {text, savedAt} JSON,回调 onConflict({remoteText, remoteSavedAt})
 *   - 不同 key → 忽略
 *   - 解析失败 / 字段类型不对 → 忽略(容错:可能有别的代码也写 nexus-draft-* 系列)
 *   - unmount / projectId 变化 → 移除旧 listener,装新 listener
 *
 * 调用方(ChatArea)拿到 onConflict 后:
 *   - 弹 toast.warn(8000ms)— useToast store 不支持 actions,所以降级为纯文本提示
 *     用户手动复制/恢复(useToast API 仅 (kind, message, durationMs))
 *
 * draftKey 复用策略:
 *   - 计划说 useDraft.ts 未 export draftKey(私有函数,避免循环依赖)
 *   - 本文件内独立定义一份 — 与 useDraft.ts 完全一致;如果 useDraft.ts 改
 *     了 key 命名规则,这里需要同步改。WHY 注释保留以便 grep 追踪。
 */
import { useEffect } from 'react'

/** Per-project storage key — 与 useDraft.ts 内 draftKey 一致(私有复制)。 */
const draftKey = (projectId: string | null | undefined): string =>
  `nexus-draft-${projectId ?? '_none'}`

export interface RemoteDraft {
  remoteText: string
  remoteSavedAt: number
}

export interface UseDraftConflictOptions {
  projectId: string | null | undefined
  onConflict: (remote: RemoteDraft) => void
}

interface DraftShape {
  text?: unknown
  savedAt?: unknown
}

export function useDraftConflict({
  projectId,
  onConflict,
}: UseDraftConflictOptions): void {
  useEffect(() => {
    const key = draftKey(projectId)
    const handler = (e: StorageEvent): void => {
      // 只关心同 key 的更新 — 不同 project 的 nexus-draft-other 与我们无关
      if (e.key !== key) return
      // 同 tab 写入不会触发 storage 事件(浏览器原生保证);不需判断 storageArea
      if (!e.newValue || e.newValue === e.oldValue) return
      try {
        const parsed = JSON.parse(e.newValue) as DraftShape
        if (typeof parsed.text !== 'string') return
        onConflict({
          remoteText: parsed.text,
          remoteSavedAt:
            typeof parsed.savedAt === 'number' ? parsed.savedAt : Date.now(),
        })
      } catch {
        /* 非 nexus-draft-* JSON 格式,忽略 */
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [projectId, onConflict])
}