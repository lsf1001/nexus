/**
 * 发送客户端 hook。
 *
 * 拆出原因:handleSend / handleRetry / handleClarificationSubmit 在原 ChatArea 里
 * 是 3 个函数,共享同一段"input 校验 + WS readyState 检查 + setLoading +
 * armWatchdog + 推 user / 空 assistant + sendRef.current()"模板。这里抽成单参数
 * 的 inline helper,加一个唯一的 useChatSend 出口。
 */

import { useCallback } from 'react';
import type { WSMessage } from '../../../types';
import type { LastError, SendFn } from '../types';

export interface UseChatSendArgs {
  /** 当前 WS 是否已连接(redux / useStore 选择器) */
  wsConnected: boolean;
  /** 检查 WS readyState(避免"鬼影消息") */
  getReadyState: () => number;
  /** 当前会话 id(undefined / null = 新会话) */
  getSessionId: () => string | null | undefined;
  /** 出站 send:已是 useWsConnection 返回的 send */
  send: SendFn;
  setIsLoading: (loading: boolean) => void;
  setLastError: (err: LastError | null) => void;
  clearInput: () => void;
  armWatchdog: () => void;
  /** 把 userMsg 推入列表(自带空 assistant 占位) */
  pushUserAndPlaceholder: (userMsg: import('../../../types').Message) => void;
}

/**
 * 单一发送入口(供 textarea 回车 / send 按钮 / 澄清表单 / 重试共用)。
 *
 * 行为不变(与原 handleSend 等价):
 *   1. trim 内容,空 / WS 未连 / readyState !== OPEN → setLastError 并 return
 *   2. setIsLoading(true) + armWatchdog() + 清 input
 *   3. push user + 空 assistant,确保流式 chunk 有地方写
 *   4. 拼 WSMessage,新会话带 title(<=30 字),旧会话带 session_id
 *   5. send(msg)
 */
export function useChatSend(args: UseChatSendArgs) {
  const {
    wsConnected,
    getReadyState,
    getSessionId,
    send,
    setIsLoading,
    setLastError,
    clearInput,
    armWatchdog,
    pushUserAndPlaceholder,
  } = args;

  return useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (!trimmed) return;
      if (!wsConnected) {
        setLastError({ message: '连接尚未就绪，请稍后再试', retryable: true, code: 'ws_not_open', at: Date.now() });
        return;
      }
      if (getReadyState() !== 1 /* WebSocket.OPEN */) {
        setLastError({ message: '连接尚未就绪，请稍后再试', retryable: true, code: 'ws_not_open', at: Date.now() });
        return;
      }
      setIsLoading(true);
      armWatchdog();
      setLastError(null);
      clearInput();

      const userMsg: import('../../../types').Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: trimmed,
        createdAt: new Date(),
      };
      pushUserAndPlaceholder(userMsg);

      const msg: WSMessage = { content: trimmed };
      const sid = getSessionId();
      if (!sid) {
        msg.title = trimmed.slice(0, 30);
      } else {
        msg.session_id = sid;
      }
      send(msg);
    },
    [wsConnected, getReadyState, getSessionId, send, setIsLoading, setLastError, clearInput, armWatchdog, pushUserAndPlaceholder],
  );
}
