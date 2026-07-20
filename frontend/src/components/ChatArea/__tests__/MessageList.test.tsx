/**
 * MessageList memo 比较器回归测试 — 2026-07-20 真 LLM 多轮暴露产品 bug。
 *
 * 背景:MessageList 原比较器只比前 N-1 条引用相等,把"最后一条 content
 * 增量"的更新责任下放给 ChatBubble 自身的默认 memo。但 React 默认 memo
 * 对 props.message 走 Object.is 浅比较,流式帧之间 message 引用不变
 * (新 array 但同位置同一对象),所以 ChatBubble 也跳过 re-render →
 * DOM 不更新,真实 LLM chunk 一直空白。
 *
 * 修法:比较器把最后一条 content / thinking / toolCalls 也按值比对。
 *
 * 本测试两层覆盖:
 * 1. 直接调用 messageListPropsAreEqual 校验逻辑分支(快、确定)。
 * 2. 端到端:渲染 MessageList + rerender,验证最后一条 content 增量能传到 DOM。
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MessageList } from '../MessageList';
import {
  messageListPropsAreEqual,
  type MessageListProps,
} from '../messageListProps';
import type { Message } from '../../../types';

function msg(id: string, content: string, extra: Partial<Message> = {}): Message {
  return {
    id,
    role: 'assistant',
    content,
    thinking: '',
    createdAt: new Date('2026-07-20T00:00:00Z'),
    ...extra,
  };
}

function makeProps(messages: Message[]): MessageListProps {
  return { messages, showThinking: false, isLoading: false };
}

describe('messageListPropsAreEqual 比较器', () => {
  it('isLoading 变化 → 不相等', () => {
    const a: MessageListProps = { messages: [], showThinking: false, isLoading: false };
    const b: MessageListProps = { ...a, isLoading: true };
    expect(messageListPropsAreEqual(a, b)).toBe(false);
  });

  it('showThinking 变化 → 不相等', () => {
    const a: MessageListProps = { messages: [], showThinking: false, isLoading: false };
    const b: MessageListProps = { ...a, showThinking: true };
    expect(messageListPropsAreEqual(a, b)).toBe(false);
  });

  it('消息数量变化 → 不相等', () => {
    const a = makeProps([msg('a', 'hi')]);
    const b = makeProps([msg('a', 'hi'), msg('b', 'hello')]);
    expect(messageListPropsAreEqual(a, b)).toBe(false);
  });

  it('前 N-1 条引用相同 + 最后一条无字段变化 → 相等', () => {
    const stable = [msg('a', 'hi'), msg('b', 'hello')];
    expect(messageListPropsAreEqual(makeProps(stable), makeProps(stable))).toBe(true);
  });

  it('最后一条 content 变化 → 不相等(关键 bug 回归点)', () => {
    const prev = makeProps([msg('a', 'hi'), msg('b', 'hello')]);
    const next = makeProps([
      prev.messages[0]!,
      msg('b', 'hello world'),
    ]);
    expect(messageListPropsAreEqual(prev, next)).toBe(false);
  });

  it('最后一条 thinking 变化 → 不相等', () => {
    const prev = makeProps([msg('a', 'hi'), msg('b', 'p', { thinking: '思考 1' })]);
    const next = makeProps([
      prev.messages[0]!,
      msg('b', 'p', { thinking: '思考 2' }),
    ]);
    expect(messageListPropsAreEqual(prev, next)).toBe(false);
  });

  it('最后一条 toolCalls 数组引用变化 → 不相等', () => {
    const prev = makeProps([msg('a', 'hi'), msg('b', 'p')]);
    const next = makeProps([
      prev.messages[0]!,
      msg('b', 'p', { toolCalls: [{ id: 't1', name: 'x', args: {}, status: 'pending' }] }),
    ]);
    expect(messageListPropsAreEqual(prev, next)).toBe(false);
  });

  it('前 N-1 条中任一引用变化 → 不相等', () => {
    const a1 = msg('a', 'hi');
    const b1 = msg('b', 'hello');
    const prev = makeProps([a1, b1]);
    const a2 = msg('a', 'hi 改');
    const next = makeProps([a2, b1]);
    expect(messageListPropsAreEqual(prev, next)).toBe(false);
  });

  it('空 messages → 相等', () => {
    expect(messageListPropsAreEqual(makeProps([]), makeProps([]))).toBe(true);
  });
});

describe('MessageList 端到端 memo', () => {
  it('流式帧之间最后一条 content 增量传到 DOM', () => {
    const base: Message[] = [
      msg('u1', '你是谁?'),
      msg('a1', 'pong!'),
    ];
    const { container, rerender } = render(
      <MessageList messages={base} showThinking={false} isLoading={false} />,
    );

    // 流式帧:第一条引用不变,第二条 content 增长
    const streaming: Message[] = [
      base[0]!,
      msg('a1', 'pong! 有什么可以帮你的吗?'),
    ];
    rerender(
      <MessageList messages={streaming} showThinking={false} isLoading={false} />,
    );

    // DOM 应反映新 content — 取最后一个 .message-markdown(对应最后一条 assistant)
    const allMarkdowns = container.querySelectorAll('.message-markdown');
    const lastMarkdown = allMarkdowns[allMarkdowns.length - 1];
    expect(lastMarkdown?.textContent).toContain('有什么可以帮你的吗');
  });

  it('同引用 props 不抛错', () => {
    const stable: Message[] = [
      msg('u1', 'hi'),
      msg('a1', 'hello'),
    ];
    const { container, rerender } = render(
      <MessageList messages={stable} showThinking={false} isLoading={false} />,
    );

    const markdownCount = container.querySelectorAll('.message-markdown').length;
    rerender(
      <MessageList messages={stable} showThinking={false} isLoading={false} />,
    );
    expect(container.querySelectorAll('.message-markdown').length).toBe(markdownCount);
    expect(container.querySelectorAll('.loading-bubble').length).toBe(0);
  });
});