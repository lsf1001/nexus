/**
 * 发送客户端 hook。
 *
 * 拆出原因:handleSend / handleRetry / handleClarificationSubmit 在原 ChatArea 里
 * 是 3 个函数,共享同一段"input 校验 + WS readyState 检查 + setLoading +
 * armWatchdog + 推 user / 空 assistant + sendRef.current()"模板。这里抽成单参数
 * 的 inline helper,加一个唯一的 useChatSend 出口。
 *
 * Round 6.1 Task 11:WS send 帧携带 style。
 *   - 旧会话:getSessionId() 返回 sid,从 useStore.getState().sessionStyles[sid] 读
 *     当前风格(默认 'default'),始终写进 WSMessage.style(不 omit)。
 *   - 新会话:getSessionId() 返回 null/undefined 时不携带 style 字段 —
 *     等首次消息落库后由后端默认 'default',下次会话回写即可同步。
 *   - 始终传(default 也写):让后端 _resolve_session_style 路径直接命中,
 *     不依赖 DB 持久值或 ws_session_state 隐式 fallthrough,减少心智负担
 *     和 fallthrough 边界 case(SPEC §4.10 / Round 6.1 Task 11 决策)。
 *   - style 不进入 useCallback deps — 读的是 store.getState() 快照而非 React state,
 *     hook 重渲染不会因为 style 变化重建 send,避免级联重建 ChatAreaActions。
 */

import { useCallback, useRef } from 'react';
import type { WSMessage } from '../../../types';
import { useStore } from '../../../store';
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
 * 单一发送入口(供 textarea 回车 / send 按钮 / 澄清表单 / 重试 / 附件提交共用)。
 *
 * 行为(与原 handleSend 等价):
 *   1. trim 内容 + 检查附件 ids,空 / WS 未连 / readyState !== OPEN → setLastError 并 return
 *   2. setIsLoading(true) + armWatchdog() + 清 input
 *   3. push user + 空 assistant,确保流式 chunk 有地方写
 *   4. 拼 WSMessage,新会话带 title(<=30 字;纯附件时 fallback "附件消息"),旧会话带 session_id
 *   5. 附件 ids 非空时挂到 WSMessage.attachment_ids(后端 sessions.build_prompt 拼 multi-part)
 *   6. send(msg)
 *
 * 第十三轮(2026-07-30):扩成 `(content, attachmentIds?)` 双参;1 参调用等价旧行为。
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

  // ref 桥接:读取最新值但不进入 useCallback deps,
  // 避免 wsConnected 每次变化都重建 send → 级联重建 useChatAreaActions。
  const wsConnectedRef = useRef(wsConnected);
  wsConnectedRef.current = wsConnected;
  const getReadyStateRef = useRef(getReadyState);
  getReadyStateRef.current = getReadyState;

  return useCallback(
    (content: string, attachmentIds?: readonly string[]) => {
      const trimmed = content.trim();
      // 无文本 + 无附件 → 等价空消息,不发
      const idsArr = attachmentIds ?? [];
      if (!trimmed && idsArr.length === 0) return;
      if (!wsConnectedRef.current) {
        setLastError({ message: '连接尚未就绪，请稍后再试', retryable: true, code: 'ws_not_open', at: Date.now() });
        return;
      }
      if (getReadyStateRef.current() !== 1 /* WebSocket.OPEN */) {
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
        msg.title = trimmed ? trimmed.slice(0, 30) : '附件消息';
      } else {
        msg.session_id = sid;
      }
      // 第十三轮:透传 attachment_ids(仅在非空时加字段 — 后端 sessions.build_prompt
      // 用 truthy 判断,空数组 / 缺字段等价"无附件",走纯 text 路径零回归)。
      if (idsArr.length > 0) {
        msg.attachment_ids = [...idsArr];
      }
      // Round 6.1 Task 11:旧会话始终携带 style。读 useStore.getState() 而非 hook
      // 闭包,避免把 sessionStyles 加进 deps 引发 useCallback 频繁重建 → ChatAreaActions
      // 级联重建。getState() 取当下快照,用户在下一次 send 前切换风格也会被新帧读到。
      // getSessionId() 已被侧效分支写回 sid,这里直接复用。
      if (sid) {
        const storeState = useStore.getState();
        const style = storeState.sessionStyles[sid] ?? 'default';
        msg.style = style;
      }
      send(msg);
    },
    [getSessionId, send, setIsLoading, setLastError, clearInput, armWatchdog, pushUserAndPlaceholder],
  );
}
