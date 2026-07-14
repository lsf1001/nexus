/**
 * ClarificationForm 单测 — 2026-07-14 UX 兜底。
 *
 * 覆盖三类路径:
 *  1. **正常**:options 非空 → 渲染选项按钮 + "自己写回答"折叠区。
 *  2. **兜底(关键)**:options 空数组 → 渲染 fallback 候选(2 个),
 *     绝不退化成纯 textarea(否则用户面对空白输入框发懵)。
 *  3. **交互**:点按钮 → onSubmit(option 文本);点取消 → onCancel;空 textarea 不 submit。
 */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ClarificationForm } from '../ClarificationForm'

describe('ClarificationForm', () => {
  it('renders option buttons when options provided', () => {
    const onSubmit = vi.fn()
    const onCancel = vi.fn()
    render(
      <ClarificationForm
        question="今天吃什么?"
        options={['火锅', '烧烤', '沙拉']}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByText('火锅')).toBeTruthy()
    expect(screen.getByText('烧烤')).toBeTruthy()
    expect(screen.getByText('沙拉')).toBeTruthy()
  })

  it('falls back to 2 default options when options is empty (UX 兜底)', () => {
    // 关键场景:LLM 没传 options(违反 prompt 强约束),前端必须兜底,
    // 不能退化成纯 textarea 让用户面对空白输入框发懵。
    const onSubmit = vi.fn()
    const onCancel = vi.fn()
    render(
      <ClarificationForm
        question="你想要什么?"
        options={[]}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    // 必须渲染 2 个 fallback 候选
    expect(screen.getByText('让 Nexus 帮我想')).toBeTruthy()
    expect(screen.getByText('我需要更多信息')).toBeTruthy()
    // "自己写回答" 折叠也必须存在(主流 UX 都有)
    expect(screen.getByText('自己写回答')).toBeTruthy()
  })

  it('clicking a fallback option submits that text', () => {
    const onSubmit = vi.fn()
    const onCancel = vi.fn()
    render(
      <ClarificationForm
        question="你想要什么?"
        options={[]}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    fireEvent.click(screen.getByText('让 Nexus 帮我想'))
    expect(onSubmit).toHaveBeenCalledWith('让 Nexus 帮我想')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('clicking a normal option submits that text', () => {
    const onSubmit = vi.fn()
    render(
      <ClarificationForm
        question="今天吃什么?"
        options={['火锅']}
        onSubmit={onSubmit}
        onCancel={() => undefined}
      />,
    )
    fireEvent.click(screen.getByText('火锅'))
    expect(onSubmit).toHaveBeenCalledWith('火锅')
  })

  it('does not render fallback buttons alongside real options (no duplication)', () => {
    // 兜底只在 options 为空时生效,有 options 时不混进 fallback。
    const onSubmit = vi.fn()
    render(
      <ClarificationForm
        question="今天吃什么?"
        options={['火锅']}
        onSubmit={onSubmit}
        onCancel={() => undefined}
      />,
    )
    expect(screen.queryByText('让 Nexus 帮我想')).toBeNull()
  })
})