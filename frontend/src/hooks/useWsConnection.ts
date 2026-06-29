import { useTauriWs } from './useTauriWs';
import { useWebSocket } from './useWebSocket';
import type { StreamEvent } from '../types';

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
 */
interface UseWsConnectionOptions {
  url: string;
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
  onMessage,
}: UseWsConnectionOptions): UseWsConnectionResult {
  const isTauri =
    typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  // 两个 hook 都调(无论 enabled),React 要求 hooks 调用顺序稳定。
  // enabled=false 的 effect 早返回,不建连;enabled=true 的 hook 建连。
  // 用三元选返回值 — isTauri 在组件生命周期内不变,hooks 顺序稳定。
  const tauri = useTauriWs<StreamEvent>({ url, onMessage, enabled: isTauri });
  const browser = useWebSocket<StreamEvent>({
    url,
    onMessage,
    enabled: !isTauri,
  });

  // 合并 isTauri 字段(子 hook 返回值不含它,但 UseWsConnectionResult 要求暴露)
  return { ...(isTauri ? tauri : browser), isTauri };
}