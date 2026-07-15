/**
 * ChatBubble 思考块折叠锁测试 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop / ChatGPT 默认折叠 agent 思考,只露"已思考 N 字"摘要。
 * 第八轮 ChatBubble thinking 默认全文展示,长思考挤爆 viewport。
 *
 * 契约:
 *   - 默认折叠成 .thinking-toggle(显示"已思考 N 字")+ 隐藏 .thinking-content
 *   - 点 toggle → 展开 .thinking-content
 *   - 再点 → 折叠
 *   - 用户偏好持久到 localStorage key 'nexus_thinking_expanded'
 *   - showThinking=false 时不渲染任何折叠 UI(原有契约)
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import ChatBubble from '../ChatBubble'
import type { Message } from '../../types'

// 第九轮:jsdom 在某些 vitest 启动模式下不注入 globalThis.localStorage
// (会报 "ExperimentalWarning: localStorage is not available")。
// 这里在 test 启动时建一个内存 storage 兜底,让 ChatBubble 的折叠偏好可读可写。
const memStore = new Map<string, string>()
const memStorage: Storage = {
  get length() {
    return memStore.size
  },
  clear: () => memStore.clear(),
  getItem: (k) => (memStore.has(k) ? memStore.get(k)! : null),
  key: (i) => Array.from(memStore.keys())[i] ?? null,
  removeItem: (k) => {
    memStore.delete(k)
  },
  setItem: (k, v) => {
    memStore.set(k, String(v))
  },
}
beforeEach(() => {
  memStore.clear()
  vi.stubGlobal('localStorage', memStorage)
})

function makeMsg(overrides: Partial<Message> = {}): Message {
  return {
    id: 'msg-1',
    role: 'assistant',
    content: 'reply',
    createdAt: new Date('2026-07-16T10:00:00'),
    ...overrides,
  }
}

beforeEach(() => {
  try {
    localStorage.clear()
  } catch {
    // jsdom 局部不可用时忽略 — setup.ts 也有兜底
  }
})

describe('ChatBubble 思考块折叠 (第九轮)', () => {
  it('有 thinking 时渲染折叠 toggle,默认隐藏 content', () => {
    const msg = makeMsg({ thinking: '我要先分析问题再回答' })
    const { container } = render(<ChatBubble message={msg} showThinking />)
    const toggle = container.querySelector('.thinking-toggle')
    expect(toggle).not.toBeNull()
    expect(toggle?.textContent).toContain('已思考')
    // content 默认不渲染
    expect(container.querySelector('.thinking-content')).toBeNull()
  })

  it('点 toggle → 展开 thinking content', () => {
    const msg = makeMsg({ thinking: '我要先分析问题再回答' })
    const { container } = render(<ChatBubble message={msg} showThinking />)
    const toggle = container.querySelector('.thinking-toggle') as HTMLElement
    fireEvent.click(toggle)
    const content = container.querySelector('.thinking-content')
    expect(content).not.toBeNull()
    expect(content?.textContent).toContain('我要先分析问题再回答')
  })

  it('再点 toggle → 折叠', () => {
    const msg = makeMsg({ thinking: '我要先分析问题再回答' })
    const { container } = render(<ChatBubble message={msg} showThinking />)
    const toggle = container.querySelector('.thinking-toggle') as HTMLElement
    fireEvent.click(toggle) // 展开
    fireEvent.click(toggle) // 再点折叠
    expect(container.querySelector('.thinking-content')).toBeNull()
  })

  it('toggle 文本含字数摘要', () => {
    const thinking = '一'.repeat(123) // 123 字
    const msg = makeMsg({ thinking })
    const { container } = render(<ChatBubble message={msg} showThinking />)
    const toggle = container.querySelector('.thinking-toggle')
    expect(toggle?.textContent).toContain('123')
  })

  it('showThinking=false → 不渲染折叠 UI', () => {
    const msg = makeMsg({ thinking: '长思考' })
    const { container } = render(<ChatBubble message={msg} showThinking={false} />)
    expect(container.querySelector('.thinking-toggle')).toBeNull()
    expect(container.querySelector('.thinking-content')).toBeNull()
  })

  it('localStorage nexus_thinking_expanded=true → 默认展开', () => {
    localStorage.setItem('nexus_thinking_expanded', 'true')
    const msg = makeMsg({ thinking: '自动展开' })
    const { container } = render(<ChatBubble message={msg} showThinking />)
    expect(container.querySelector('.thinking-content')).not.toBeNull()
  })

  it('展开后写 localStorage (供下次默认展开)', () => {
    const msg = makeMsg({ thinking: 'test' })
    const { container } = render(<ChatBubble message={msg} showThinking />)
    const toggle = container.querySelector('.thinking-toggle') as HTMLElement
    fireEvent.click(toggle)
    expect(localStorage.getItem('nexus_thinking_expanded')).toBe('true')
    fireEvent.click(toggle)
    expect(localStorage.getItem('nexus_thinking_expanded')).toBe('false')
  })
})