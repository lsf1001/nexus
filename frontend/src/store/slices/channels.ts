import type { StateCreator } from 'zustand';
import type { ChannelType, ConfirmationAction } from '../../types';

/** 通道收件箱里的一条消息(独立于主会话,避免串台污染)。 */
export interface ChannelInboxMsg {
  id: string;
  user_id: string;
  content: string;
  timestamp: number;
}

/** HITL 待审批挂起项 — 后端 GraphInterrupt → 前端确认卡片。
 *  与澄清挂起(pendingClarification)互斥:同时只允许一种挂起态展示在 UI。 */
export interface PendingConfirmation {
  interruptId: string;
  eventId: number;
  actions: ConfirmationAction[];
}

/**
 * 多通道收件箱 + HITL 挂起切片 — 业务数据,不持久化。
 *
 * channelInbox 按 channelType 分桶,与主会话消息隔离(取代旧 wechatInbox:
 * Message[])。pendingConfirmation 由后端 GraphInterrupt 帧推入,用户
 * resolve / cancel 后清空。
 */
export interface ChannelsSlice {
  channelInbox: Record<string, ChannelInboxMsg[]>;
  pendingConfirmation: PendingConfirmation | null;
  addChannelInbox: (channelType: ChannelType, msg: ChannelInboxMsg) => void;
  clearChannelInbox: (channelType: ChannelType) => void;
  setPendingConfirmation: (p: PendingConfirmation | null) => void;
}

export const createChannelsSlice: StateCreator<ChannelsSlice, [], [], ChannelsSlice> = (set) => ({
  channelInbox: {},
  pendingConfirmation: null,
  addChannelInbox: (channelType, msg) =>
    set((state) => ({
      channelInbox: {
        ...state.channelInbox,
        [channelType]: [...(state.channelInbox[channelType] ?? []), msg],
      },
    })),
  clearChannelInbox: (channelType) =>
    set((state) => ({
      channelInbox: { ...state.channelInbox, [channelType]: [] },
    })),
  setPendingConfirmation: (p) => set({ pendingConfirmation: p }),
});