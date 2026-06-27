import { useEffect, useRef, useState } from 'react';

interface UseWebSocketOptions<T> {
  url: string;
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
      const ws = new WebSocket(url);
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
        try {
          onMessageRef.current(JSON.parse(data) as T);
        } catch {
          // 非 JSON 消息（如纯文本），原样透传
          onMessageRef.current(data as unknown as T);
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
  }, [url, baseDelay, maxDelay, heartbeatInterval, reconnect, enabled]);

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
