import { useEffect, useRef, useState } from 'react';
import { invoke, Channel } from '@tauri-apps/api/core';

interface UseTauriWsOptions<T> {
  url: string;
  /** WS 鉴权 token;走 Rust relay 时作为 invoke 参数独立传(2026-07 改造,token 不再进 URL)。 */
  token: string;
  onMessage: (data: T) => void;
  enabled?: boolean;
}

interface UseTauriWsResult {
  connected: boolean;
  send: (data: unknown) => Promise<void>;
  getReadyState: () => number;
}

// 与 useWebSocket 兼容的常量(WS 协议不变,后端 StreamEvent 形状一致)
const WS_OPEN = 1;
const WS_CLOSED = 3;

/**
 * Tauri Channel 版 WebSocket hook。
 * 替代 useWebSocket.ts,把 WS 流式经 Rust relay 转发。
 *
 * 接口与 useWebSocket 兼容(connected + send + getReadyState),
 * 但实际连接到 Rust 进程,不直接连 FastAPI。
 *
 * 重连由 Rust supervisor 负责(进程级),不在前端重试,
 * 因为 sidecar 崩溃会自动重启,WS session 由 ws_close 显式关。
 *
 * 鉴权(2026-07 改造):token 不再拼到 URL ?token=,改作为 invoke 参数独立传;
 * Rust relay 走 `Sec-WebSocket-Protocol: nexus-v1.token=<token>` 子协议头
 * 完成 WS 升级握手(与浏览器原生 `new WebSocket(url, subprotocols)` 等价)。
 */
export function useTauriWs<T = unknown>({
  url,
  token,
  onMessage,
  enabled = true,
}: UseTauriWsOptions<T>): UseTauriWsResult {
  const [connected, setConnected] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        // URL 转绝对地址:Rust relay 期望 ws://127.0.0.1:30000/...
        const fullUrl = url.startsWith('ws')
          ? url
          : `ws://127.0.0.1:30000${url.startsWith('/') ? '' : '/'}${url}`;

        // ws_open 绑定的 Channel 是 Rust relay 把后端 WS 响应转回前端的唯一通道。
        // 必须把每条消息转交给 ChatArea 的 handleWsMessage，否则后端已完成
        // 但前端永远收不到 final/done/error，会一直停在 loading 转圈。
        const openChunk = new Channel<T>();
        openChunk.onmessage = (message) => {
          onMessageRef.current(message);
        };

        const sessionId = await invoke<string>('ws_open', {
          url: fullUrl,
          token,
          onChunk: openChunk,
        });
        if (cancelled) {
          // 组件已卸载,立即关闭
          invoke('ws_close', { sessionId }).catch(() => {});
          return;
        }
        sessionRef.current = sessionId;
        setConnected(true);
      } catch (e) {
        // 启动失败,转 error 消息给 onMessage(后端 stream 协议兼容)
        // 带 error_code=ws_open_failed + content + retryable,
        // 前端 setLastError 能区分 'ws 启动失败'(retryable=true →
        // '暂时不可用')与 'LLM 错误'(retryable=false → '请求失败')。
        //
        // WHY 不直接 String(e):invoke 抛的 Error message 含 invoke 参数,
        // 例如 `ws token is empty;请在启动时注入 NEXUS_WS_TOKEN` 或 stack。
        // 这是用户输入/配置问题,用统一文案既不漏诊断,也避免泄露路径。
        // WHY 用 console.warn 而非新建 logger:前端 console 已被 Vite / 浏览器
        // devtools 收集,生产走 Tauri webview 时进 ~/.nexus/logs/webview-error.log
        // (见 desktop/src-tauri/src/main.rs log_webview_error),足够定位。
        // 不引入 logger 库,与现有"不造轮子"约定一致。
        console.warn('ws_open failed', e);
        onMessageRef.current({
          type: 'error',
          error_code: 'ws_open_failed',
          content: 'WS 启动失败,请检查后端状态和 token 配置',
          retryable: true,
        } as unknown as T);
      }
    })();

    return () => {
      cancelled = true;
      const sessionId = sessionRef.current;
      if (sessionId) {
        sessionRef.current = null;
        invoke('ws_close', { sessionId }).catch(() => {});
      }
    };
  }, [url, token, enabled]);

  const send = async (data: unknown): Promise<void> => {
    const sessionId = sessionRef.current;
    if (!sessionId) throw new Error('ws not connected');

    // ws_relay.rs 简化版:ws_open 时一次性绑 channel + 长期 rx_task,
    // ws_send 只发 payload,响应统一从 onChunk 进 onMessage。
    // 不再每次 send 新建 Channel — 生命周期 = ws session。
    await invoke('ws_send', {
      sessionId,
      payload: data,
    });
  };

  const getReadyState = (): number => {
    return sessionRef.current ? WS_OPEN : WS_CLOSED;
  };

  return { connected, send, getReadyState };
}