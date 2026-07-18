/**
 * 空态视图:hero + prompt 卡片网格 + 状态卡。
 *
 * 拆出原因:ChatArea 老的 isIdle 分支 JSX 90 行,自带右键菜单触发和上下文状态,
 * 单独抽出让 ChatArea function body 只负责编排。
 *
 * 输入框已统一到底部 Composer(ChatArea 层渲染),本组件只负责引导内容。
 */

import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { QUICK_PROMPTS } from './constants';

export interface EmptyStateProps {
  modelName: string;
  connectionState: 'connecting' | 'online' | 'offline';
  activeConversationTitle: string | null;
  conversationCount: number;
  onInsertPrompt: (text: string) => void;
  onSubmit: (text: string) => void;
}

export function EmptyState({
  modelName,
  connectionState,
  activeConversationTitle,
  conversationCount,
  onInsertPrompt,
}: EmptyStateProps) {
  return (
    <div className="empty-state flex w-full max-w-3xl flex-col items-center gap-10 px-6 py-16">
      <div className="hero flex flex-col items-center gap-3 text-center">
        <div className="eyebrow text-xs font-medium uppercase tracking-wide text-muted-foreground">
          个人任务助手
        </div>
        <h1 className="hero-title-2xl text-balance font-semibold tracking-tight text-foreground">
          今天想让我帮你做什么？
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
          Nexus 会在后台理解任务、选择模型、整理上下文和记录必要信息。
          你只需要把事情交给它。
        </p>
      </div>

      <div className="prompt-grid grid w-full max-w-2xl grid-cols-2 gap-3">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt.title}
            type="button"
            className="prompt-card rounded-xl border border-border bg-card px-4 py-3 text-left text-sm font-medium text-foreground/90 transition hover:border-primary/40 hover:bg-accent"
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
        className="status-card w-full max-w-2xl rounded-xl border border-border bg-card/60 px-4 py-3 text-xs text-muted-foreground"
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
        <strong className="text-foreground/90">任务状态</strong>
        <div className="row mt-2 flex items-center justify-between gap-2">
          <span className="label text-muted-foreground">助手</span>
          <span className="value text-foreground/90">{modelName || '未配置模型'}</span>
        </div>
        <div className="row flex items-center justify-between gap-2">
          <span className="label text-muted-foreground">本地连接</span>
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
        <div className="row flex items-center justify-between gap-2">
          <span className="label text-muted-foreground">当前会话</span>
          <span className="value text-foreground/90">{activeConversationTitle || '新任务（未保存）'}</span>
        </div>
        <div className="row flex items-center justify-between gap-2">
          <span className="label text-muted-foreground">最近任务</span>
          <span className="value text-foreground/90">{conversationCount} 条</span>
        </div>
      </div>
    </div>
  );
}
