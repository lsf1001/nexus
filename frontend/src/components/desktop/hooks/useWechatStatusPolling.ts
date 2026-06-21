import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../../../lib/api';

const POLL_INTERVAL_MS = 10_000;

/**
 * 微信通道绑定状态轮询。
 * 守卫 1:每个轮询周期只允许一个 in-flight 请求;前一个未结束就 abort 掉。
 * 守卫 2:组件卸载时 abort。
 */
export function useWechatStatusPolling(): {
  wechatConnected: boolean;
} {
  const [wechatConnected, setWechatConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const check = (): void => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      apiFetch('/api/channels/wechat/bind', { signal: controller.signal })
        .then((response) => response.json())
        .then((data: { bound: boolean; status?: string }) => {
          if (abortRef.current !== controller) return;
          setWechatConnected(data.bound && data.status === 'running');
        })
        .catch(() => {
          if (abortRef.current !== controller) return;
          setWechatConnected(false);
        });
    };

    check();
    const timer = window.setInterval(check, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  return { wechatConnected };
}
