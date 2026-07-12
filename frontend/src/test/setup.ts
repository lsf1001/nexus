/**
 * vitest 全局 setup — 引入 jest-dom matcher + 重置 Zustand store 状态。
 *
 * 每个测试用 `beforeEach` 调 resetStore 把 store 还原到默认(防止 slice 间
 * 持久化残留 — persist middleware 把 darkMode 写到 localStorage,如果
 * 不清会让 `useStore` 不同 snapshot 互相干扰)。
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import { useStore } from '../store'

afterEach(() => {
  cleanup()
})

beforeEach(() => {
  // store 是模块级单例,每个 test 还原。slice 字段全覆盖到默认 + 清 localStorage。
  useStore.setState({
    darkMode: false,
    showThinking: true,
    wsConnected: false,
    wsStatus: 'closed',
    reconnectAttempts: 0,
    conversationMessages: [],
    models: [],
    currentModelId: '',
    modelName: '',
    isLoading: false,
    channelInbox: {},
    pendingConfirmation: null,
  } as never)
  // Persist middleware 写的 localStorage 清掉,避免跨 test 状态污染
  try {
    localStorage.clear()
  } catch {
    // jsdom 不可用时忽略 — only happens in pathological env
  }
})
