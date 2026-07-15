/**
 * handleToolCall / handleToolResult 单测 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:第八轮 tool_call / tool_result 帧在 wsHandlers.ts 是 noop,前端看不到
 * agent 在调什么工具。第九轮:tool_call → append ToolCall(state=running)
 * 到当前 assistant message 的 toolCalls 数组;tool_result → 更新对应 ToolCall
 * 的 result + state(success / error)。
 *
 * 测试通过 useStore.setConversationMessages() 预置 assistant placeholder,
 * 调 handler,断言 store 里 toolCalls 字段被正确写入/更新。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '../../../store';
import { handleToolCall, handleToolResult } from '../hooks/wsHandlers';
import type { WsRouterCtx } from '../hooks/wsHandlers';
import type { StreamEvent } from '../../../types';

function makeCtx(): WsRouterCtx {
  return {
    stream: {
      ensureAssistantPlaceholder: () => false,
      appendToAssistant: () => undefined,
      pushUserAndPlaceholder: () => undefined,
      replaceAssistantWithPlaceholder: () => undefined,
      reset: () => undefined,
      snapshot: () => useStore.getState().conversationMessages,
      markUserStopped: () => undefined,
      allowsStreaming: () => true,
    },
    setLastError: () => undefined,
    setIsLoading: () => undefined,
    setPendingClarification: () => undefined,
    setPendingConfirmation: () => undefined,
    disarmWatchdog: vi.fn(),
  };
}

describe('handleToolCall / handleToolResult (第九轮)', () => {
  beforeEach(() => {
    useStore.getState().setConversationMessages([
      {
        id: 'a1',
        role: 'assistant',
        content: '',
        createdAt: new Date(),
      },
    ]);
  });

  it('tool_call 帧 → append ToolCall(running) 到最后一条 assistant.toolCalls', () => {
    const ctx = makeCtx();
    const ev: StreamEvent = {
      type: 'tool_call',
      content: JSON.stringify({ id: 'tc-1', name: 'shell_run', args: { command: 'ls' } }),
      session_id: 's1',
    };
    handleToolCall(ev, ctx);
    const msgs = useStore.getState().conversationMessages;
    const last = msgs[msgs.length - 1]!;
    expect(last.toolCalls?.length).toBe(1);
    expect(last.toolCalls?.[0]?.name).toBe('shell_run');
    expect(last.toolCalls?.[0]?.state).toBe('running');
    expect(last.toolCalls?.[0]?.args).toEqual({ command: 'ls' });
  });

  it('多次 tool_call → 累积到同一 assistant message 的 toolCalls', () => {
    const ctx = makeCtx();
    handleToolCall(
      {
        type: 'tool_call',
        content: JSON.stringify({ id: 'tc-1', name: 'shell_run', args: {} }),
        session_id: 's1',
      },
      ctx
    );
    handleToolCall(
      {
        type: 'tool_call',
        content: JSON.stringify({ id: 'tc-2', name: 'read_file', args: { path: '/x' } }),
        session_id: 's1',
      },
      ctx
    );
    const msgs = useStore.getState().conversationMessages;
    const last = msgs[msgs.length - 1]!;
    expect(last.toolCalls?.length).toBe(2);
    expect(last.toolCalls?.[0]?.name).toBe('shell_run');
    expect(last.toolCalls?.[1]?.name).toBe('read_file');
  });

  it('tool_result 帧 → 更新对应 ToolCall 的 result + state(success)', () => {
    const ctx = makeCtx();
    handleToolCall(
      {
        type: 'tool_call',
        content: JSON.stringify({ id: 'tc-1', name: 'shell_run', args: {} }),
        session_id: 's1',
      },
      ctx
    );
    handleToolResult(
      {
        type: 'tool_result',
        content: JSON.stringify({ id: 'tc-1', result: 'hello', error: null }),
        session_id: 's1',
      },
      ctx
    );
    const msgs = useStore.getState().conversationMessages;
    const last = msgs[msgs.length - 1]!;
    expect(last.toolCalls?.[0]?.state).toBe('success');
    expect(last.toolCalls?.[0]?.result).toBe('hello');
  });

  it('tool_result.error → state=error + result 写错误信息', () => {
    const ctx = makeCtx();
    handleToolCall(
      {
        type: 'tool_call',
        content: JSON.stringify({ id: 'tc-1', name: 'shell_run', args: {} }),
        session_id: 's1',
      },
      ctx
    );
    handleToolResult(
      {
        type: 'tool_result',
        content: JSON.stringify({ id: 'tc-1', result: '', error: 'Permission denied' }),
        session_id: 's1',
      },
      ctx
    );
    const msgs = useStore.getState().conversationMessages;
    expect(msgs[msgs.length - 1]?.toolCalls?.[0]?.state).toBe('error');
    expect(msgs[msgs.length - 1]?.toolCalls?.[0]?.result).toBe('Permission denied');
  });

  it('tool_result 找不到对应 id → noop(不抛错)', () => {
    const ctx = makeCtx();
    handleToolCall(
      {
        type: 'tool_call',
        content: JSON.stringify({ id: 'tc-1', name: 'shell_run', args: {} }),
        session_id: 's1',
      },
      ctx
    );
    expect(() =>
      handleToolResult(
        {
          type: 'tool_result',
          content: JSON.stringify({ id: 'tc-XXX', result: 'orphan' }),
          session_id: 's1',
        },
        ctx
      )
    ).not.toThrow();
  });

  it('tool_call 时没有 assistant placeholder → noop(不抛错)', () => {
    useStore.getState().setConversationMessages([]);
    const ctx = makeCtx();
    expect(() =>
      handleToolCall(
        {
          type: 'tool_call',
          content: JSON.stringify({ id: 'tc-1', name: 'shell_run', args: {} }),
          session_id: 's1',
        },
        ctx
      )
    ).not.toThrow();
  });
});