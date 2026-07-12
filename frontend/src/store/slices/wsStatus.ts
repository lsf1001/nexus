import type { StateCreator } from 'zustand';

/**
 * WS 连接状态切片 — 瞬态,不持久化(Plan 3 扩了 wsStatus / reconnectAttempts,
 * Plan 4 顺手收敛到这里)。
 *
 * 不变量:
 * - setWsConnected(true/false) 与 setWsStatus 解耦:open 事件只动 connected,
 *   WsClient 重连调度只动 status / reconnectAttempts。
 * - reconnectAttempts 在 wsStatus 变 reconnecting 时**不**自动清零(WsClient
 *   内部维护归 0 计数,store 仅镜像显示)。
 */
export interface WsStatusSlice {
  wsConnected: boolean;
  /** 'connecting' | 'connected' | 'reconnecting' | 'exhausted' | 'closed' */
  wsStatus: 'connecting' | 'connected' | 'reconnecting' | 'exhausted' | 'closed';
  /** 当前重连尝试序号(WsClient 暴露,UI 显示 "重连 S3/8") */
  reconnectAttempts: number;
  setWsConnected: (connected: boolean) => void;
  setWsStatus: (status: WsStatusSlice['wsStatus']) => void;
  setReconnectAttempts: (n: number) => void;
}

export const createWsStatusSlice: StateCreator<WsStatusSlice, [], [], WsStatusSlice> = (set) => ({
  wsConnected: false,
  wsStatus: 'connecting',
  reconnectAttempts: 0,
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setWsStatus: (status) => set({ wsStatus: status }),
  setReconnectAttempts: (n) => set({ reconnectAttempts: n }),
});