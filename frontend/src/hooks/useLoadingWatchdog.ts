import { useCallback, useEffect, useRef } from 'react';

/**
 * 客户端 watchdog:防止后端不发 done/final/error 时前端一直转圈。
 *
 * 后端在以下场景可能不发终止帧:
 *   - LLM 拒答/沉默 → StreamGuard 重试 3 次后发 error,但期间前端一直转
 *   - 模型账户限流 → 同上
 *   - LLM 死循环/长 thinking → 超时但没 fail
 *
 * 用法:
 *   const { arm, disarm } = useLoadingWatchdog({ setIsLoading, setLastError });
 *   arm();        // 每次 setIsLoading(true) 之后调
 *   disarm();     // 每次收到 done/error/final/clarification_request 之后调
 *
 * 用 ref 包 setIsLoading/setLastError → 不需要进 deps,
 * arm/disarm 引用稳定,handleWsMessage 等 useCallback 不会因此重建。
 */

interface UseLoadingWatchdogOptions {
  setIsLoading: (v: boolean) => void;
  setLastError: (err: {
    message: string;
    retryable: boolean;
    code: string;
    at: number;
  } | null) => void;
  timeoutMs?: number;
}

interface UseLoadingWatchdogReturn {
  arm: () => void;
  disarm: () => void;
}

export function useLoadingWatchdog({
  setIsLoading,
  setLastError,
  timeoutMs = 90_000,
}: UseLoadingWatchdogOptions): UseLoadingWatchdogReturn {
  const timerRef = useRef<number | null>(null);
  const settersRef = useRef({ setIsLoading, setLastError, timeoutMs });
  settersRef.current = { setIsLoading, setLastError, timeoutMs };

  const disarm = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const arm = useCallback(() => {
    disarm();
    const { setIsLoading: setLoad, setLastError: setErr, timeoutMs: tmo } = settersRef.current;
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setLoad(false);
      setErr({
        message: `响应超时(${Math.round(tmo / 1000)}s),后端可能卡住或模型账户限流。请重试或检查 API key。`,
        retryable: true,
        code: 'client_watchdog_timeout',
        at: Date.now(),
      });
    }, tmo);
  }, [disarm]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  return { arm, disarm };
}