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
import type { Artifact, ArtifactKind } from '../../../store/slices/artifacts';
import { useStore } from '../../../store';
import { useToastStore } from '../../../store/useToast';

export interface WsRouterCtx {
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
  _ctx: WsRouterCtx,
  patch: Partial<{ content: string; thinking: string }>,
) => {
  // 2026-07-20:不再走 ctx.stream.appendToAssistant — 那个函数捕获 useChatStream
  // 的 useCallback([]) 闭包,在 React 19 并发 + ChatArea 高频 re-render 场景下,
  // 新 dispatcher 持新 ctx,新 ctx.stream 是 useChatStream() 返回的新对象字面量
  // (useChatStream 没用 useMemo),appendToAssistant 引用虽然 useCallback 缓存
  // 但 ctx.stream 闭包链上有 subtle timing 问题(实测 content 不写 store,thinking
  // 写)。直接走 store action 消除整条闭包链,handler 与 ctx.stream 解耦。
  useStore.getState().appendAssistantPatch(patch);
};

/**
 * Task 3.3:从 final / tool_result 帧的 content 中识别结构化 artifact。
 *
 * 标记格式(向后兼容新增,无标记时零副作用,**不改 WS 协议**):
 *   <!-- artifact kind=code lang=ts title=MyScript -->
 *   <实际内容>
 *   <!-- /artifact -->
 * kind ∈ code | markdown | svg | html;lang / title 可选(支持引号包裹)。
 *
 * 纯函数:命中返回 Artifact(id 随机,由 slice 按 id 去重),未命中返回 null。
 * 只"识别"不"改写"——消息 content 照常展示,artifact 额外进 store。
 */
const ARTIFACT_BLOCK_RE =
  /<!--\s*artifact\s+([\s\S]*?)-->\n([\s\S]*?)\n<!--\s*\/artifact\s*-->/;

const ARTIFACT_KINDS = ['code', 'markdown', 'svg', 'html'] as const;

function asArtifactKind(value: string | undefined): ArtifactKind | null {
  return ARTIFACT_KINDS.includes(value as ArtifactKind) ? (value as ArtifactKind) : null;
}

function parseArtifactAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  const re = /(\w+)=("([^"]*)"|'([^']*)'|(\S+))/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    const key = m[1] ?? '';
    if (!key) continue;
    const val = m[3] ?? m[4] ?? m[5] ?? '';
    attrs[key] = val;
  }
  return attrs;
}

export function extractArtifact(content: string): Artifact | null {
  const m = ARTIFACT_BLOCK_RE.exec(content);
  if (!m) return null;
  const attrs = parseArtifactAttrs(m[1] ?? '');
  const kind = asArtifactKind(attrs.kind);
  if (!kind) return null;
  return {
    id: crypto.randomUUID(),
    kind,
    content: m[2] ?? '',
    title: attrs.title || undefined,
    language: attrs.lang || undefined,
  };
}

export const handleThinking: WsHandler = (ev, ctx) => {
  if (typeof ev.content === 'string') {
    appendPatch(ctx, { thinking: ev.content });
  } else {
    // 兜底:即使 content 为空 / 不存在,也确保 assistant 占位存在并清空,
    // 让 handleFinal 的 last.content 校验有目标。原 ctx.stream.ensureAssistantPlaceholder()
    // 已并入 appendAssistantPatch,这里用空 patch 调用即可。
    appendPatch(ctx, {});
  }
  // 2026-07-22 修复:thinking 帧是"流还在进行"的标志 — 不应关闭 isLoading。
  // 原逻辑收到第一个 thinking 帧就 setIsLoading(false),导致 stop 按钮在 mock
  // 流 ~50ms 内就消失,Playwright 抓不到持续可见状态(journey-stop-mid-stream
  // full suite 一直 FAIL,isolated 因 React batch 时序侥幸通过)。
  // 流未结束期间(isLoading=true)保持,直到 handleFinal / handleDone / handleError。
  // armWatchdog 由 handleSend 在发消息时设,这里无需重复 arm。
  // 仍 disarmWatchdog 让 30s 兜底 watchdog 在每一帧活动时清零重计时,
  // 避免 mock 慢 / 真 LLM 慢的场景下被误清 loading。
  ctx.disarmWatchdog();
};

export const handleChunk: WsHandler = (ev, ctx) => {
  ctx.setLastError(null);
  if (typeof ev.content === 'string') {
    appendPatch(ctx, { content: ev.content });
  } else {
    appendPatch(ctx, {});
  }
  // 2026-07-22 修复:chunk 帧同 thinking — 流还在出,保持 isLoading=true,
  // 详见 handleThinking 注释。
  ctx.disarmWatchdog();
};

export const handleFinal: WsHandler = (ev, ctx) => {
  // 仅当 incoming 与当前累计内容不同时才覆盖 — 说明是 quality pipeline 替换,
  // 而非 chunks 总和(原 ChatArea 行为)。
  //
  // 2026-07-13:用户点 stop 后 appendToAssistant gate 已丢弃后续 chunk,但
  // handleFinal 直接 useStore.setState 覆盖最后一条 assistant content — 会把
  // handleStop 追加的 "[已停止]" marker 抹掉。这里必须尊重 user-stop gate,
  // 否则最终 DOM 看不到 marker,journey-stop-mid-stream spec 永远失败。
  //
  // 2026-07-20:streamingPaused 已迁到 store,直接 useStore.getState() 读,
  // 不再依赖 ctx.stream.snapshot / ctx.stream.allowsStreaming,消除闭包链。
  const state = useStore.getState();
  if (!state.conversationMessages.length || state.streamingPaused) {
    ctx.setIsLoading(false);
    ctx.disarmWatchdog();
    return;
  }
  if (typeof ev.content !== 'string') {
    ctx.setIsLoading(false);
    ctx.disarmWatchdog();
    return;
  }
  const msgs = state.conversationMessages;
  const last = msgs[msgs.length - 1];
  if (last && last.role === 'assistant' && ev.content !== last.content) {
    const next = [...msgs];
    next[next.length - 1] = { ...last, content: ev.content };
    state.setConversationMessages(next);
  }
  // Task 3.3:末尾内容识别 artifact → 追加进 artifacts slice。无标记时
  // extractArtifact 返回 null,零副作用,消息 content 不变。
  const artifact = extractArtifact(ev.content);
  if (artifact) useStore.getState().pushArtifact(artifact);
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
  // race 修复:澄清帧可能抢在占位 assistant msg 之前到达(WS mock / 会话恢复),
  // 此时 if 分支跳过 → 问题消息永远不进聊天历史。补 else 主动 push 一条新消息,
  // 保证"无论帧序如何,澄清问题都会作为可见消息落进 ref"。
  const msgs = useStore.getState().conversationMessages;
  const last = msgs[msgs.length - 1];
  if (last && last.role === 'assistant' && last.content === '') {
    const next = [...msgs];
    next[next.length - 1] = { ...last, content: `[澄清中] ${question}` };
    useStore.getState().setConversationMessages(next);
  } else {
    useStore.getState().setConversationMessages([
      ...msgs,
      {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `[澄清中] ${question}`,
        createdAt: new Date(),
      },
    ]);
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

/** 第九轮(2026-07-16):tool_call 帧 → append ToolCall(running) 到当前
 * assistant message 的 toolCalls 数组。content 是 JSON 字符串,字段:
 *   { id: string, name: string, args?: object }
 * 解析失败 → warn + noop,不抛错(后端协议演进时兼容)。 */
export const handleToolCall: WsHandler = (ev, ctx) => {
  if (typeof ev.content !== 'string') return;
  let payload: { id?: string; name?: string; args?: Record<string, unknown> };
  try {
    payload = JSON.parse(ev.content) as typeof payload;
  } catch {
    useToastStore.getState().push('warn', 'tool_call 帧 JSON 解析失败,已忽略');
    return;
  }
  if (!payload.id || !payload.name) {
    useToastStore.getState().push('warn', 'tool_call 帧缺 id / name,已忽略');
    return;
  }
  const msgs = useStore.getState().conversationMessages;
  const last = msgs[msgs.length - 1];
  if (!last || last.role !== 'assistant') return;
  const next = [...msgs];
  const existing = last.toolCalls ?? [];
  next[next.length - 1] = {
    ...last,
    toolCalls: [
      ...existing,
      { id: payload.id, name: payload.name, state: 'running', args: payload.args },
    ],
  };
  useStore.getState().setConversationMessages(next);
  // tool_call 期间 isLoading 仍为 true,继续等后续 chunk / result
  ctx.disarmWatchdog();
};

/** 第九轮:tool_result 帧 → 更新对应 ToolCall 的 result + state。
 *  content JSON:{ id, result?, error? }
 *  error 非空 → state='error' + result=error;
 *  result 字段(可能很长)— 原样存进 ToolCall.result。 */
export const handleToolResult: WsHandler = (ev, ctx) => {
  if (typeof ev.content !== 'string') return;
  let payload: { id?: string; result?: string; error?: string | null };
  try {
    payload = JSON.parse(ev.content) as typeof payload;
  } catch {
    useToastStore.getState().push('warn', 'tool_result 帧 JSON 解析失败,已忽略');
    return;
  }
  if (!payload.id) return;
  const msgs = useStore.getState().conversationMessages;
  const last = msgs[msgs.length - 1];
  if (!last || last.role !== 'assistant' || !last.toolCalls) return;
  const idx = last.toolCalls.findIndex((tc) => tc.id === payload.id);
  if (idx < 0) return;
  const hasError = typeof payload.error === 'string' && payload.error.length > 0;
  const updated: typeof last.toolCalls = last.toolCalls.map((tc, i) =>
    i === idx
      ? {
          ...tc,
          state: hasError ? 'error' : 'success',
          result: hasError ? payload.error! : payload.result ?? tc.result,
        }
      : tc
  );
  const next = [...msgs];
  next[next.length - 1] = { ...last, toolCalls: updated };
  useStore.getState().setConversationMessages(next);
  // Task 3.3:末尾内容识别 artifact(若 tool_result 帧本身带 artifact 标记)。
  const artifact = extractArtifact(ev.content);
  if (artifact) useStore.getState().pushArtifact(artifact);
  ctx.disarmWatchdog();
};

/** 兜底:token_usage / stats / resume_* 等观测帧 noop */
export const noop: WsHandler = () => undefined;
