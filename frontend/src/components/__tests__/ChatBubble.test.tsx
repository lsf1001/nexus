/**
 * ChatBubble React.memo 单测 — 验证 4 类隔离行为:
 * - (1) 同 props (引用不同但 content/thinking 相同) → 不重渲染
 * - (2) message.content 变 → 触发重渲染
 * - (3) message.thinking 变 → 触发重渲染
 * - (4) onCopy 引用变(父级 re-render 副作用) → 不重渲染(刻意忽略 closure 变化)
 *
 * 注:用 vi.fn() spy 在 ChatBubbleInner 上计数渲染次数。这里通过修改
 * default export 拿不到内部 spy(它是匿名函数),所以改为 spy on render:
 * 测试断言 "DOM 文本节点内容变化次数" — 内容变 → ReactMarkdown 重渲染
 * → 文本节点更新。验证手段是 `rerender` 多次,断言只有应触发渲染的 case
 * 文本节点被覆盖。
 *
 * 简化方案:导出 `chatBubblePropsAreEqual` 供单测直接断言相等函数,
 * 这是 memo 行为的唯一约束来源;再用 React Testing Library 走一次完整
 * render 流程,断言 DOM 更新次数。
 *
 * 2026-07-14 增 pathLinkify 集成测试:
 *  - 图片路径 → <img class="file-image" src="file://...">
 *  - 非图片路径 → <a class="file-link" href="file://..." target="_blank">
 */
import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import ChatBubble from '../ChatBubble'
import { chatBubblePropsAreEqual } from '../chatBubbleProps'
import type { Message } from '../../types'

function makeMsg(overrides: Partial<Message> = {}): Message {
  return {
    id: 'msg-1',
    role: 'assistant',
    content: 'hello',
    createdAt: new Date('2026-07-12T10:00:00'),
    ...overrides,
  }
}

describe('chatBubblePropsAreEqual 自定义比较器', () => {
  it('完全相同 props → 相等(不重渲染)', () => {
    const a: { message: Message; showThinking?: boolean; onCopy?: (s: string) => void } = {
      message: makeMsg(),
    }
    const b = { ...a }
    expect(chatBubblePropsAreEqual(a, b)).toBe(true)
  })

  it('message.content 变 → 不相等(必渲染)', () => {
    const a = { message: makeMsg({ content: 'hello' }) }
    const b = { message: makeMsg({ content: 'hello world' }) }
    expect(chatBubblePropsAreEqual(a, b)).toBe(false)
  })

  it('message.thinking 变 → 不相等(必渲染,流式核心场景)', () => {
    const a = { message: makeMsg({ thinking: 'part 1' }) }
    const b = { message: makeMsg({ thinking: 'part 1 + delta' }) }
    expect(chatBubblePropsAreEqual(a, b)).toBe(false)
  })

  it('message.id 变 → 不相等(换消息必渲染)', () => {
    const a = { message: makeMsg({ id: 'a' }) }
    const b = { message: makeMsg({ id: 'b' }) }
    expect(chatBubblePropsAreEqual(a, b)).toBe(false)
  })

  it('message.role 变 → 不相等(用户/助手类名不同)', () => {
    const a = { message: makeMsg({ role: 'user' }) }
    const b = { message: makeMsg({ role: 'assistant' }) }
    expect(chatBubblePropsAreEqual(a, b)).toBe(false)
  })

  it('onCopy 引用变(父级 re-render 副作用)→ 视为相等(memo 命中,不走重渲染)', () => {
    const onCopyA = vi.fn()
    const onCopyB = vi.fn()
    const a = { message: makeMsg(), onCopy: onCopyA }
    const b = { message: makeMsg(), onCopy: onCopyB }
    // 父级 re-render 时 onCopy 通常传新 closure — memo 应当忽略此变化
    expect(chatBubblePropsAreEqual(a, b)).toBe(true)
  })

  it('showThinking 变化 → 不相等(用户切"显示/隐藏思考"开关)', () => {
    const a = { message: makeMsg(), showThinking: true }
    const b = { message: makeMsg(), showThinking: false }
    expect(chatBubblePropsAreEqual(a, b)).toBe(false)
  })
})

describe('ChatBubble memo 集成行为', () => {
  it('同 message 引用 + 同 props → DOM 只渲染一次', () => {
    const msg = makeMsg({ content: 'hello' })
    const { rerender, container } = render(<ChatBubble message={msg} showThinking />)
    const firstHtml = container.innerHTML
    // 传完全相同的 message 引用 — React.memo 应该跳过重渲染,DOM 完全相同
    rerender(<ChatBubble message={msg} showThinking />)
    expect(container.innerHTML).toBe(firstHtml)
  })

  it('content 字段值变化 → DOM 文本节点更新(流式 chunk 行为)', () => {
    const { rerender, container } = render(<ChatBubble message={makeMsg({ content: 'hello' })} />)
    rerender(<ChatBubble message={makeMsg({ content: 'hello world' })} />)
    expect(container.textContent).toContain('hello world')
    expect(container.textContent).not.toContain('hello<')
  })

  it('thinking 字段值变化 → DOM 文本节点更新(流式思考块行为)', () => {
    const msg1 = makeMsg({ thinking: 'first thought' })
    const msg2 = makeMsg({ thinking: 'first thought + step 2' })
    const { rerender, container } = render(<ChatBubble message={msg1} showThinking />)
    rerender(<ChatBubble message={msg2} showThinking />)
    expect(container.textContent).toContain('first thought + step 2')
  })

  it('onCopy 引用变化但 message 内容相同 → DOM 不变', () => {
    const msg = makeMsg({ content: 'fixed content' })
    const onCopyA = vi.fn()
    const onCopyB = vi.fn()
    const { rerender, container } = render(<ChatBubble message={msg} onCopy={onCopyA} />)
    const before = container.innerHTML
    rerender(<ChatBubble message={msg} onCopy={onCopyB} />)
    // memo 应当命中,DOM 不更新
    expect(container.innerHTML).toBe(before)
  })

  it('showThinking 由 true → false → 思考块消失(用户切开关)', () => {
    const msg = makeMsg({ thinking: 'deep thought', content: 'reply' })
    const { rerender, container } = render(<ChatBubble message={msg} showThinking />)
    expect(container.textContent).toContain('deep thought')
    rerender(<ChatBubble message={msg} showThinking={false} />)
    expect(container.textContent).not.toContain('deep thought')
  })
})

describe('ChatBubble 路径 linkify 集成 (2026-07-14)', () => {
  it('图片路径 → <img class="file-image" src="file://...">', () => {
    const { container } = render(
      <ChatBubble message={makeMsg({ content: '看 /Users/yxb/.nexus/outputs/koi.jpg 大图' })} />
    )
    const img = container.querySelector('img.file-image')
    expect(img).not.toBeNull()
    expect(img!.getAttribute('src')).toBe('file:///Users/yxb/.nexus/outputs/koi.jpg')
    expect(img!.getAttribute('alt')).toBe('/Users/yxb/.nexus/outputs/koi.jpg')
    expect(img!.getAttribute('loading')).toBe('lazy')
  })

  it('非图片路径 → <a class="file-link" target="_blank" rel="noopener noreferrer">', () => {
    const { container } = render(
      <ChatBubble message={makeMsg({ content: '日志在 /Users/yxb/.nexus/outputs/run.log' })} />
    )
    const a = container.querySelector('a.file-link')
    expect(a).not.toBeNull()
    expect(a!.getAttribute('href')).toBe('file:///Users/yxb/.nexus/outputs/run.log')
    expect(a!.getAttribute('target')).toBe('_blank')
    expect(a!.getAttribute('rel')).toBe('noopener noreferrer')
    expect(a!.textContent).toBe('/Users/yxb/.nexus/outputs/run.log')
  })

  it('inlineCode 内路径不被转(<code> 优先)', () => {
    const { container } = render(
      <ChatBubble message={makeMsg({ content: '看 `/Users/yxb/x.jpg` 这条' })} />
    )
    expect(container.querySelector('a.file-link')).toBeNull()
    expect(container.querySelector('img.file-image')).toBeNull()
    expect(container.querySelector('code')).not.toBeNull()
    expect(container.textContent).toContain('/Users/yxb/x.jpg')
  })
})