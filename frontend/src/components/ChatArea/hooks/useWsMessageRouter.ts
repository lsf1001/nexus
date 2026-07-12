/**
 * WS 帧分派器。
 *
 * 拆出原因:原 ChatArea.handleWsMessage 是 172 行 switch,9 个 case 共享一份
 * ref 同步状态,不好测试也很难改。改用 Record<WsFrame['type'], WsHandler> 形式,
 * 每个 case 在 wsHandlers.ts 单独一个纯函数 + 一个共享 ctx(包含 action 集合 /
 * setter / onSessionCreated 等)。
 *
 * 不变量:
 *   - thinking/chunk/final 帧到达时确保最后一条是 assistant 占位(write in handler)
 *   - 每个会改变"loading"的 case 都调 disarmWatchdog,避免 watchdog 30s 后误清
 *   - channel_message 帧走 store.channelInbox(不变更主消息流)
 *   - clarification_request 会回填"刚刚问了 X"占位文案,与 DB 历史一致
 *
 * 引用稳定性:由 ChatArea function body 用 useMemo 包 WsRouterCtx 注入,本 hook
 * 才能 useCallback([ctx]) 保持 dispatcher 引用稳定 — useWsConnection 内部
 * useWebSocket / useTauriWs 的 onMessage effect 才能避免每次 render 重连。
 */

import { useCallback } from 'react';
import type { StreamEvent } from '../../../types';
import {
  handleChannelMessage,
  handleClarificationRequest,
  handleChunk,
  handleConfirmationRequest,
  handleDone,
  handleError,
  handleFinal,
  handleSessionCreated,
  handleThinking,
  noop,
  type WsHandler,
  type WsRouterCtx,
} from './wsHandlers';

// Re-export WsRouterCtx 让 index.tsx 能从 useWsMessageRouter 拿,避免外层依赖 wsHandlers。
export type { WsRouterCtx };

const HANDLERS: Readonly<Record<StreamEvent['type'], WsHandler>> = {
  thinking: handleThinking,
  chunk: handleChunk,
  tool_call: noop,
  tool_result: noop,
  final: handleFinal,
  done: handleDone,
  error: handleError,
  token_usage: noop,
  channel_message: handleChannelMessage,
  session_created: handleSessionCreated,
  resume_token: noop,
  resume_ack: noop,
  invalid_resume_token: noop,
  stats: noop,
  clarification_request: handleClarificationRequest,
  confirmation_request: handleConfirmationRequest,
};

/**
 * 顶层 dispatcher hook。
 *
 * useWsConnection.onMessage 拿到的可能是任意 unknown,这里先做最浅的 shape check,
 * 再走查表派发;type 不在表内时 noop(防御性 — 后端若新增帧类型,前端默认吞掉)。
 */
export function useWsMessageRouter(ctx: WsRouterCtx): (raw: unknown) => void {
  return useCallback(
    (raw: unknown) => {
      if (!raw || typeof raw !== 'object' || !('type' in raw)) return;
      const ev = raw as StreamEvent;
      const handler = HANDLERS[ev.type];
      if (!handler) return;
      handler(ev, ctx);
    },
    [ctx],
  );
}
