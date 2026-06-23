/**
 * useChannelStatusPolling - 通用轮询通道绑定状态。
 *
 * 取代 useWechatStatusPolling,接受 channelType 参数动态拼接 URL。
 * 守卫 1:每个轮询周期只允许一个 in-flight 请求;前一个未结束就 abort 掉。
 * 守卫 2:组件卸载时 abort。
 */

import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { ChannelType } from '../types';

const POLL_INTERVAL_MS = 3_000;

export interface ChannelBindStatus {
  bound: boolean;
  account_id?: string;
  status?: string;
  need_rescan?: boolean;
}

export function useChannelStatusPolling(channelType: ChannelType): ChannelBindStatus | null {
  const [status, setStatus] = useState<ChannelBindStatus | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;

    const check = (): void => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      apiFetch(`/api/channels/${channelType}/bind`, { signal: controller.signal })
        .then((response) => response.json() as Promise<ChannelBindStatus>)
        .then((data) => {
          if (cancelled || abortRef.current !== controller) return;
          setStatus(data);
        })
        .catch(() => {
          if (cancelled || abortRef.current !== controller) return;
          setStatus({ bound: false });
        });
    };

    check();
    const timer = window.setInterval(check, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [channelType]);

  return status;
}
