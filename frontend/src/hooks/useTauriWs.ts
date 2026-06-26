import { useEffect, useRef, useState } from 'react';
import { invoke, Channel } from '@tauri-apps/api/core';

interface UseTauriWsOptions<T> {
  url: string;
  onMessage: (data: T) => void;
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
 */
export function useTauriWs<T = unknown>({
  url,
  onMessage,
}: UseTauriWsOptions<T>): UseTauriWsResult {
  const [connected, setConnected] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        // URL 转绝对地址:Rust relay 期望 ws://127.0.0.1:30000/...
        const fullUrl = url.startsWith('ws')
          ? url
          : `ws://127.0.0.1:30000${url.startsWith('/') ? '' : '/'}${url}`;

        const sessionId = await invoke<string>('ws_open', { url: fullUrl });
        if (cancelled) {
          // 组件已卸载,立即关闭
          invoke('ws_close', { sessionId }).catch(() => {});
          return;
        }
        sessionRef.current = sessionId;
        setConnected(true);
      } catch (e) {
        // 启动失败,转 error 消息给 onMessage(后端 stream 协议兼容)
        onMessageRef.current({
          type: 'error',
          data: String(e),
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
  }, [url]);

  const send = async (data: unknown): Promise<void> => {
    const sessionId = sessionRef.current;
    if (!sessionId) throw new Error('ws not connected');

    // 每次 send 都新建 Channel,Rust 端会启动一个新 rx task
    // 直到收到 type:"done" 自动 break
    const onChunk = new Channel<T>();
    onChunk.onmessage = (msg) => {
      onMessageRef.current(msg);
    };

    await invoke('ws_send', {
      sessionId,
      payload: data,
      onChunk,
    });
  };

  const getReadyState = (): number => {
    return sessionRef.current ? WS_OPEN : WS_CLOSED;
  };

  return { connected, send, getReadyState };
}