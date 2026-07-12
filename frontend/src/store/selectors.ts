/**
 * 跨切片派生 selector — 让组件只订阅派生结果,避免宽订阅触发 re-render。
 *
 * 设计:每个 selector 用 `useStore((s) => ...)` 取派生值,Zustand 默认对
 * 引用相等做 shallow 比较。返回**新对象 / 新函数** 的 selector 会让
 * React 误判每次都变 — 因此每个 selector 都返回基础类型(string /
 * boolean)或已存在的引用(Message[] / PendingConfirmation),不在 selector
 * 内做 .map / .filter 重新构造。
 *
 * 性能影响:Plan 4 §Phase 4 + 跟 Plan 2 React.memo 配套,组件 re-render
 * 受 selector 派生依赖控制。
 */
import { useStore } from './index';

/** 当前重连状态为 reconnecting 时显示 "S{n}/8" 标签,否则返回 null(隐藏)。 */
export function useWsReconnectLabel(): string | null {
  return useStore((s) => {
    if (s.wsStatus !== 'reconnecting') return null;
    return `S${s.reconnectAttempts}/8`;
  });
}

/** HITL 确认卡片显示条件(pendingConfirmation != null)。 */
export function useHasPendingConfirmation(): boolean {
  return useStore((s) => Boolean(s.pendingConfirmation));
}

/** 当前激活模型名(空时显示 '未配置')。 */
export function useActiveModelName(): string {
  return useStore((s) => s.modelName || '未配置');
}