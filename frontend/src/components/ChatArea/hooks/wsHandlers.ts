/**
 * WS 帧 handler 实现集合。
 *
 * 每个 handler 是 (ev, ctx) => void 纯函数,纯靠 ctx(setter + stream 操作集
 * + toast) 完成副作用,不含任何 React 状态。便于 Plan 2 Phase vitest 单测与未来
 * Server Components / Web Worker 复用。
 *
 * 类型边界:
 *   - ev:StreamEvent 的 type 是 union,但默认 handler 想跑更窄的语义化处理时,
 *     在 handler 内部 narrow 而不强制外层 cast。这里类型用 StreamEvent,由
 *     外层 dispatcher(narrow → 派发)保证 type 已 narrowing。
 *   - ctx:WsRouterCtx 由 ChatArea function body 注入。
 */

import type { StreamEvent, ConfirmationAction } from '../../../types';
import type { LastError } from '../types';
import type { ChatStreamActions } from './useChatStream';
import { useStore } from '../../../store/useStore';
import { useToastStore } from '../../../store/useToast';

export interface WsRouterCtx {
  stream: ChatStreamActions;
  setLastError: (err: LastError | null) => void;
  setIsLoading: (loading: boolean) => void;
  setPendingClarification: (
    pc: { question: string; options: string[] } | null,
  ) => void;
  setPendingConfirmation: (
    pc: {
      interruptId: string;
      eventId: number;
      actions: ConfirmationAction[];
    } | null,
  ) => void;
  disarmWatchdog: () => void;
  onSessionCreated?: (sessionId: string, title: string) => void;
}

export type WsHandler = (ev: StreamEvent, ctx: WsRouterCtx) => void;

const appendPatch = (
  ctx: WsRouterCtx,
  patch: Partial<{ content: string; thinking: string }>,
) => {
  ctx.stream.ensureAssistantPlaceholder();
  ctx.stream.appendToAssistant(patch);
};

export const handleThinking: WsHandler = (ev, ctx) => {
  if (typeof ev.content === 'string') {
    appendPatch(ctx, { thinking: ev.content });
  } else {
    ctx.stream.ensureAssistantPlaceholder();
  }
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
};

export const handleChunk: WsHandler = (ev, ctx) => {
  ctx.setLastError(null);
  if (typeof ev.content === 'string') {
    appendPatch(ctx, { content: ev.content });
  } else {
    ctx.stream.ensureAssistantPlaceholder();
  }
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
};

export const handleFinal: WsHandler = (ev, ctx) => {
  // 仅当 incoming 与当前累计内容不同时才覆盖 — 说明是 quality pipeline 替换,
  // 而非 chunks 总和(原 ChatArea 行为)。
  if (typeof ev.content !== 'string') {
    ctx.setIsLoading(false);
    ctx.disarmWatchdog();
    return;
  }
  const msgs = useStore.getState().conversationMessages;
  const last = msgs[msgs.length - 1];
  if (last && last.role === 'assistant' && ev.content !== last.content) {
    const next = [...msgs];
    next[next.length - 1] = { ...last, content: ev.content };
    useStore.getState().setConversationMessages(next);
  }
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
};

export const handleDone: WsHandler = (_ev, ctx) => {
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
};

export const handleError: WsHandler = (ev, ctx) => {
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
  ctx.setLastError({
    message: ev.content || '未知错误',
    retryable: ev.retryable ?? false,
    code: ev.error_code || 'unknown',
    at: Date.now(),
  });
};

export const handleChannelMessage: WsHandler = (ev, _ctx) => {
  // channel_message 不进主消息流,分桶到 store.channelInbox — 等同侧栏收件箱图标
  // 显示对应通道数量,用户主动点开对应通道视图才看具体内容(取代旧 wechat_message 单通道帧)。
  if (!ev.channel_type) return;
  useStore.getState().addChannelInbox(ev.channel_type, {
    id: crypto.randomUUID(),
    user_id: ev.user_id || '',
    content: ev.content || '',
    timestamp: Date.now(),
  });
};

export const handleSessionCreated: WsHandler = (ev, ctx) => {
  ctx.onSessionCreated?.(ev.session_id || '', ev.title || '新会话');
};

export const handleClarificationRequest: WsHandler = (ev, ctx) => {
  // LLM 主动追问:弹澄清表单等用户回答。澄清是 LLM turn 内的挂起点,
  // 不是独立 turn,所以要清 loading + disarm watchdog(否则 30s 后误清)。
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
  const question = (ev.content || '').trim() || 'AI 需要你确认一项';
  const options = Array.isArray(ev.options)
    ? ev.options
        .filter((opt): opt is string => typeof opt === 'string' && opt.trim().length > 0)
        .slice(0, 6)
    : [];
  // 回填"[澄清中]"占位文案到 assistant 气泡,与 DB 历史一致,会话回放不丢上下文。
  const msgs = useStore.getState().conversationMessages;
  const last = msgs[msgs.length - 1];
  if (last && last.role === 'assistant' && last.content === '') {
    const next = [...msgs];
    next[next.length - 1] = { ...last, content: `[澄清中] ${question}` };
    useStore.getState().setConversationMessages(next);
  }
  ctx.setPendingClarification({ question, options });
};

export const handleConfirmationRequest: WsHandler = (ev, ctx) => {
  // HITL 桥接:LLM 触发敏感操作审批,与澄清不同,HITL 是阻断 LLM turn 的真正挂起点。
  ctx.setIsLoading(false);
  ctx.disarmWatchdog();
  if (!Array.isArray(ev.actions) || ev.actions.length === 0) {
    useToastStore.getState().push('warn', '后端 confirmation_request 缺少 actions 字段,已忽略');
    return;
  }
  ctx.setPendingConfirmation({
    interruptId: ev.interrupt_id || '',
    eventId: ev.event_id || 0,
    actions: ev.actions,
  });
};

/** 兜底:tool_call / tool_result / token_usage / stats / resume_* 等观测帧 noop */
export const noop: WsHandler = () => undefined;
