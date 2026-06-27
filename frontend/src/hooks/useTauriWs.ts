import { useEffect, useRef, useState } from 'react';
import { invoke, Channel } from '@tauri-apps/api/core';

interface UseTauriWsOptions<T> {
  url: string;
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
 */
export function useTauriWs<T = unknown>({
  url,
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

        // ws_open 在 Rust 端要求 onChunk 参数(签名约束),但实际响应转发由
        // ws_send 启动的临时 rx_task + 临时 Channel 完成(每次 send 独立),
        // ws_open 这里不真正用 channel —— 但 Tauri IPC 严格按签名校验,
        // 缺 onChunk 会抛 'missing required key onChunk',前端 catch 发
        // type:'error' data:String(e),error_code 空 → 前端 setLastError
        // 显示 '未知错误'。所以这里建一个占位 channel 满足签名校验。
        const openChunk = new Channel<T>();
        openChunk.onmessage = () => {
          /* 占位:ws_open 不产生响应 */
        };

        const sessionId = await invoke<string>('ws_open', {
          url: fullUrl,
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
        onMessageRef.current({
          type: 'error',
          error_code: 'ws_open_failed',
          content: String(e),
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
  }, [url, enabled]);

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
