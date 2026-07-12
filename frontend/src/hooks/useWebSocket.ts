import { useEffect, useRef, useState } from 'react';

interface UseWebSocketOptions<T> {
  url: string;
  /** Sec-WebSocket-Protocol 子协议列表(2026-07 WS 鉴权改造)。
   *  浏览器原生 `new WebSocket(url, subprotocols)` 第二参数,RFC 6455 协商。 */
  subprotocols?: string[];
  onMessage: (data: T) => void;
  /** 当前运行环境是否启用浏览器 WebSocket。 */
  enabled?: boolean;
  /** 指数退避基数（毫秒），默认 1000 */
  baseDelay?: number;
  /** 指数退避上限（毫秒），默认 30000 */
  maxDelay?: number;
  /** 心跳 ping 间隔（毫秒），默认 25000；设 0 关闭 */
  heartbeatInterval?: number;
  /** 关闭时是否自动重连，默认 true */
  reconnect?: boolean;
}

export function useWebSocket<T = unknown>({
  url,
  subprotocols,
  onMessage,
  baseDelay = 1000,
  maxDelay = 30000,
  heartbeatInterval = 25000,
  reconnect = true,
  enabled = true,
}: UseWebSocketOptions<T>): {
  connected: boolean;
  send: (data: unknown) => void;
  getReadyState: () => number;
} {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const heartbeatRef = useRef<number | null>(null);
  const cancelledRef = useRef(false);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }

    cancelledRef.current = false;

    const clearTimers = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (heartbeatRef.current !== null) {
        window.clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
    };

    const connect = () => {
      if (cancelledRef.current) return;
      // subprotocols 传 `['nexus-v1.token=...']`,token 不进 URL;
      // 服务端走 nexus.backend.api.ws.auth._extract_ws_token 解析。
      const ws = subprotocols?.length
        ? new WebSocket(url, subprotocols)
        : new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
        if (heartbeatInterval > 0) {
          heartbeatRef.current = window.setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              try { ws.send('ping'); } catch { /* ignore */ }
            }
          }, heartbeatInterval);
        }
      };

      ws.onmessage = (event) => {
        const data = event.data;
        if (typeof data === 'string' && data === 'ping') return; // 忽略后端心跳
        if (typeof data !== 'string') {
          // Blob / ArrayBuffer — 后端 stream 协议约定只发 JSON 文本帧,
          // 非文本帧一律丢弃,避免触发下游误分支。
          return;
        }
        try {
          onMessageRef.current(JSON.parse(data) as T);
        } catch {
          // 非 JSON 文本帧(例如错误代理 HTML):丢弃,不透传。
          // 历史 fallback 会把 raw data 当 T 传给 onMessage,
          // ChatArea handleWsMessage switch on 'type' 找不到匹配 → 静默吞掉,
          // 用户看不到任何反馈。直接丢弃更安全,后端 ping/pong 也走 JSON。
          console.warn('ws dropped non-JSON frame');
        }
      };

      ws.onerror = () => {
        // 浏览器 onerror 后必触发 onclose，统一在 onclose 处理重连
      };

      ws.onclose = () => {
        setConnected(false);
        clearTimers();
        if (cancelledRef.current || !reconnect) return;
        const delay = Math.min(maxDelay, baseDelay * 2 ** retryRef.current);
        retryRef.current += 1;
        timerRef.current = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      cancelledRef.current = true;
      clearTimers();
      wsRef.current?.close();
    };
    // subprotocols 依赖:useMemo 在 useWsConnection 层保证数组引用稳定,
    // 但我们这里仍要"内容变了就连一次" → 用 join 后字符串作为依赖。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, subprotocols?.join('|'), baseDelay, maxDelay, heartbeatInterval, reconnect, enabled]);

  const send = (data: unknown) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  };

  // 暴露 readyState 查询：避免在 ws 抖动期间发"鬼影消息"。
  // 返回值对应 WebSocket 的 4 个 readyState 之一（CONNECTING/OPEN/CLOSING/CLOSED）。
  const getReadyState = (): number => {
    const ws = wsRef.current;
    return ws ? ws.readyState : WebSocket.CLOSED;
  };

  return { connected, send, getReadyState };
}