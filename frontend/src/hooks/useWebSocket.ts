import { useEffect, useRef, useState } from 'react';
import { WsClient } from '../lib/ws/WsClient';

interface UseWebSocketOptions<T> {
  url: string;
  /** Sec-WebSocket-Protocol 子协议列表(2026-07 WS 鉴权改造)。
   *  浏览器原生 `new WebSocket(url, subprotocols)` 第二参数,RFC 6455 协商。 */
  subprotocols?: string[];
  onMessage: (data: T) => void;
  /** 当前运行环境是否启用浏览器 WebSocket。 */
  enabled?: boolean;
  /** 退避基数(毫秒),默认 1000 */
  baseDelay?: number;
  /** 退避上限(毫秒),默认 30000 */
  maxDelay?: number;
  /** 最大重试次数,默认 8(累计 ~5min)。0 = 失败即停 */
  maxRetries?: number;
  /** 重试用尽回调 — useStore.setWsStatus('exhausted') 或类似 */
  onExhausted?: () => void;
}

export function useWebSocket<T = unknown>({
  url,
  subprotocols,
  onMessage,
  baseDelay = 1000,
  maxDelay = 30000,
  maxRetries = 8,
  onExhausted,
  enabled = true,
}: UseWebSocketOptions<T>): {
  connected: boolean;
  send: (data: unknown) => void;
  getReadyState: () => number;
} {
  const [connected, setConnected] = useState(false);
  const clientRef = useRef<WsClient | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }

    const factory = (target: string, protocols?: string[]) => {
      const ws = new WebSocket(target, protocols);
      // 结构类型匹配:WsClient 用 IWebSocketLike 形状,WebSocket 实例满足。
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ws as any;
    };

    const client = new WsClient({
      url,
      subprotocols,
      socketFactory: factory,
      onMessage: (data) => onMessageRef.current(data as T),
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      policy: {
        baseDelayMs: baseDelay,
        maxDelayMs: maxDelay,
        maxRetries,
        onExhausted: onExhausted ?? (() => undefined),
      },
    });
    clientRef.current = client;
    client.connect();

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, subprotocols?.join('|'), baseDelay, maxDelay, maxRetries, enabled]);

  const send = (data: unknown) => {
    const client = clientRef.current;
    if (!client) return;
    const payload = typeof data === 'string' ? data : JSON.stringify(data);
    client.send(payload);
  };

  const getReadyState = (): number => clientRef.current?.getReadyState() ?? WebSocket.CLOSED;

  return { connected, send, getReadyState };
}