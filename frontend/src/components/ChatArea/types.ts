/**
 * ChatArea 内部类型定义。
 *
 * 拆出原因:LastError / PendingClarification 只服务组件内,不污染全局 types。
 */

import type { ConfirmationAction, ConfirmationResponseFrame, StreamEvent } from '../../types';

export interface LastError {
  message: string;
  retryable: boolean;
  code: string;
  at: number;
}

/** LLM 主动追问时弹的澄清卡片所需字段(question + 0-6 个候选项,空 → 自由输入) */
export interface PendingClarification {
  question: string;
  options: string[];
}

/** 客户端发送入口签名(handleSend / handleRetry / handleClarificationSubmit 都用它) */
export type SendFn = (msg: { content: string; session_id?: string; title?: string }) => void;

/** WS 帧联合别名(实际 type 是 StreamEvent['type'],这里收窄方便 dispatcher 分发) */
export type WsFrame = StreamEvent;

/** HITL 回包帧(类型与全局 ConfirmationResponseFrame 一致,这里暴露给子模块) */
export type ConfirmationResponsePayload = ConfirmationResponseFrame;

/** HITL 入参项的本地别名(用全局 ConfirmationAction) */
export type { ConfirmationAction };
