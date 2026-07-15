/**
 * ToolCallCard — 第九轮(2026-07-16)agent 工具调用透明卡。
 *
 * WHY:Claude Desktop / ChatGPT 把 agent 调用的工具 / 参数 / 结果直接展在
 * 消息流,让用户看到"为什么这个回复等了 8 秒"——在调什么工具、参数对不对、
 * 结果是什么。第八轮这些帧在 wsHandlers 是 noop,用户看不到 agent 内部行为。
 *
 * 形态(SPEC 3.5):
 *   - 默认折叠成一行:🔧 name · state
 *   - 点 ▾ → 展开 args(JSON) + result(text)
 *   - state 颜色:running(灰)/ success(森林绿)/ error(深红)
 *
 * 不放权限弹窗(HITL 由 ConfirmationCard 单独处理),只读展示。
 */
import { useState } from 'react';
import type { ToolCall } from '../../types';

export interface ToolCallCardProps {
  call: ToolCall;
}

const STATE_LABEL: Record<ToolCall['state'], string> = {
  running: '运行中',
  success: '成功',
  error: '失败',
};

const STATE_ICON: Record<ToolCall['state'], string> = {
  running: '⏳',
  success: '✓',
  error: '✕',
};

export function ToolCallCard({ call }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const argsJson = call.args ? JSON.stringify(call.args, null, 2) : '{}';
  return (
    <div className="tool-call-card">
      <button
        type="button"
        className="tool-call-header"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={`工具 ${call.name} ${STATE_LABEL[call.state]} · 点开看详情`}
      >
        <span className="tool-call-icon" aria-hidden="true">🔧</span>
        <span className="tool-call-name">{call.name}</span>
        <span className={`tool-call-state is-${call.state}`}>
          <span aria-hidden="true">{STATE_ICON[call.state]}</span>
          {' '}
          {STATE_LABEL[call.state]}
        </span>
        <span className="tool-call-toggle" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
      </button>
      {expanded && (
        <div className="tool-call-details">
          <div className="tool-call-section">
            <div className="tool-call-section-label">参数</div>
            <div className="tool-call-args">
              <code>{argsJson}</code>
            </div>
          </div>
          {call.result !== undefined && (
            <div className="tool-call-section">
              <div className="tool-call-section-label">结果</div>
              <div className="tool-call-result">
                <pre>{call.result}</pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}