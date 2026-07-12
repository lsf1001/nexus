/**
 * 空态视图:hero + prompt 卡片网格 + 状态卡。
 *
 * 拆出原因:ChatArea 老的 isIdle 分支 JSX 90 行,自带右键菜单触发和上下文状态,
 * 单独抽出让 ChatArea function body 只负责编排。
 */

import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { QUICK_PROMPTS } from './constants';

export interface EmptyStateProps {
  modelName: string;
  connectionState: 'connecting' | 'online' | 'offline';
  activeConversationTitle: string | null;
  conversationCount: number;
  onInsertPrompt: (text: string) => void;
}

export function EmptyState({
  modelName,
  connectionState,
  activeConversationTitle,
  conversationCount,
  onInsertPrompt,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="hero">
        <div className="eyebrow">个人任务助手</div>
        <h1>今天想让我帮你做什么？</h1>
        <p>
          Nexus 会在后台理解任务、选择模型、整理上下文和记录必要信息。
          你只需要把事情交给它。
        </p>
      </div>

      <div className="prompt-grid">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt.title}
            type="button"
            className="prompt-card"
            onClick={() => onInsertPrompt(prompt.prompt)}
            onContextMenu={(e) =>
              openContextMenuAt(e, `${prompt.title}\n${prompt.prompt}`, '速记')
            }
          >
            {prompt.title}
          </button>
        ))}
      </div>

      <div
        className="status-card"
        onContextMenu={(e) =>
          openContextMenuAt(
            e,
            [
              '任务状态',
              `助手: ${modelName || '未配置模型'}`,
              `本地连接: ${connectionState === 'online' ? '运行中' : connectionState === 'connecting' ? '连接中' : '离线'}`,
              `当前会话: ${activeConversationTitle || '新任务（未保存）'}`,
              `最近任务: ${conversationCount} 条`,
            ].join('\n'),
            '状态',
          )
        }
      >
        <strong>任务状态</strong>
        <div className="row">
          <span className="label">助手</span>
          <span className="value">{modelName || '未配置模型'}</span>
        </div>
        <div className="row">
          <span className="label">本地连接</span>
          <span className="value">
            <span
              className={`state-pill ${connectionState === 'online' ? '' : 'is-idle'}`}
            >
              {connectionState === 'online'
                ? '运行中'
                : connectionState === 'connecting'
                  ? '连接中'
                  : '离线'}
            </span>
          </span>
        </div>
        <div className="row">
          <span className="label">当前会话</span>
          <span className="value">{activeConversationTitle || '新任务（未保存）'}</span>
        </div>
        <div className="row">
          <span className="label">最近任务</span>
          <span className="value">{conversationCount} 条</span>
        </div>
      </div>
    </div>
  );
}
