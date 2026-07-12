import { useMemo } from 'react';
import { useTauriWs } from './useTauriWs';
import { useWebSocket } from './useWebSocket';
import type { StreamEvent } from '../types';

/**
 * RFC 7230 §3.2.6 token ABNF:`=` 与 `.` 都是 delimiter,不在 tchar 内,Chromium ≥149
 * 严格校验。修复后短前缀 `nxv1-` + base64url token(字符集 `[A-Za-z0-9-_]` 全在
 * tchar 内),整个 subprotocol 字符串字面合规。
 */
function encodeWsTokenSubprotocol(token: string): string {
  // btoa 对非 ASCII 抛;token 通常是 ASCII / base64 / hex,这里 fallback 用
  // encodeURIComponent 保证 utf-8 字符也能正确编码成 ASCII 串。
  const b64 = (typeof btoa !== 'undefined'
    ? btoa(unescape(encodeURIComponent(token)))
    : ''
  )
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `nxv1-${b64}`;
}

/**
 * WebSocket 连接适配层 — 集中 Tauri / 浏览器两种实现的选择逻辑。
 *
 * 为什么不直接拆子组件(在 ChatArea 用 isTauri 条件渲染)?
 *   ChatArea 814 行已超单文件 800 行约束,再拆 2 个子组件 + props 透传
 *   会让 diff 翻倍。先用适配层收敛 import + 选择逻辑,后续若
 *   ChatArea 进一步拆分,可把本 hook 拆成两个独立子组件再各自调
 *   对应的实现。
 *
 * 为什么这里两个 hook 都调?
 *   React 规则禁止"条件分支 / 循环里调 hook",所以 isTauri 不能直接
 *   控制调哪个 hook。两个 hook 都调,各自 effect 在 enabled=false 时
 *   早返回,只建一个连接。代价是 useState / useRef 状态对多一份,
 *   约 200B,可忽略。
 *
 * WS 鉴权(2026-07 改造):token 通过 `token` 入参传入,适配层按环境分派:
 * - Tauri:作为 `ws_open` invoke 参数独立传给 Rust relay
 * - 浏览器:填入 `Sec-WebSocket-Protocol: nxv1-<base64url(token)>` 子协议头
 * 两条路径都不再让 token 进 URL ?token=,避免出现在代理 access log /
 * 浏览器历史 / 错误堆栈。
 */
interface UseWsConnectionOptions {
  url: string;
  token: string;
  onMessage: (data: StreamEvent) => void;
}

interface UseWsConnectionResult {
  connected: boolean;
  send: (data: unknown) => void | Promise<void>;
  getReadyState: () => number;
  isTauri: boolean;
}

export function useWsConnection({
  url,
  token,
  onMessage,
}: UseWsConnectionOptions): UseWsConnectionResult {
  const isTauri =
    typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  // 浏览器 WS 的子协议数组:浏览器原生 new WebSocket(url, ['nxv1-<b64u>'])。
  // 用 useMemo 让引用稳定,避免 useWebSocket 依赖数组每次 render 都变,
  // 触发 useEffect 重连。空 token 不构造子协议(浏览器 dev 未注入 env 时优雅降级)。
  const subprotocols = useMemo(
    () => (token ? [encodeWsTokenSubprotocol(token)] : undefined),
    [token],
  );

  // 两个 hook 都调(无论 enabled),React 要求 hooks 调用顺序稳定。
  // enabled=false 的 effect 早返回,不建连;enabled=true 的 hook 建连。
  // 用三元选返回值 — isTauri 在组件生命周期内不变,hooks 顺序稳定。
  const tauri = useTauriWs<StreamEvent>({
    url,
    token,
    onMessage,
    enabled: isTauri,
  });
  const browser = useWebSocket<StreamEvent>({
    url,
    subprotocols,
    onMessage,
    enabled: !isTauri,
  });

  // 合并 isTauri 字段(子 hook 返回值不含它,但 UseWsConnectionResult 要求暴露)
  return { ...(isTauri ? tauri : browser), isTauri };
}