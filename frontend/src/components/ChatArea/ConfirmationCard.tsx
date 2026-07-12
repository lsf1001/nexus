/**
 * HITL 确认卡片:用户审批 / 拒绝 LLM 触发的敏感操作(写文件 / 编辑 AGENTS.md 等)。
 *
 * 设计:approve / reject 二选一(后端 ConfirmationAction 选项固定两个),
 * 点击后把 ConfirmationResponseFrame 装帧 send 出去,并清本地 pendingConfirmation。
 * Phase 1 拆出便于后续 unit test。
 */

import type { ConfirmationAction, ConfirmationResponseFrame } from '../../types';

export interface ConfirmationCardProps {
  interruptId: string;
  eventId: number;
  actions: ConfirmationAction[];
  /** 当前 WS readyState 上下文,用于发送时检查(避免在 disconnect 状态发) */
  canSend: boolean;
  /** 实际发送 outbound 帧的回调 */
  wsSend: (msg: ConfirmationResponseFrame) => void;
  /** 用户已决策后清本地状态 */
  onResolved: () => void;
}

export function ConfirmationCard({
  interruptId,
  eventId,
  actions,
  canSend,
  wsSend,
  onResolved,
}: ConfirmationCardProps) {
  return (
    <div className="confirm-card" role="group" aria-label="AI 请求你确认一项操作">
      <div className="confirm-eyebrow">需要你确认</div>
      {actions.map((action, idx) => (
        <div
          key={`${interruptId}-${idx}`}
          className="confirm-action"
        >
          <div className="confirm-action-header">
            <code className="confirm-tool">{action.tool_name}</code>
            <span className="confirm-target">{action.target_path}</span>
          </div>
          {action.description && (
            <div className="confirm-description">{action.description}</div>
          )}
          {action.preview && (
            <pre className="confirm-preview">{action.preview}</pre>
          )}
          <div className="confirm-actions">
            {action.options.map((opt) => (
              <button
                key={opt.decision}
                type="button"
                className={`confirm-btn confirm-${opt.decision}`}
                onClick={() => {
                  if (!canSend) return;
                  wsSend({
                    type: 'confirmation_response',
                    event_id: eventId,
                    interrupt_id: interruptId,
                    decision: opt.decision,
                  });
                  onResolved();
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
