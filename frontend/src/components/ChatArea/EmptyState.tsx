/**
 * 空态视图:hero 标题 + 描述 + 4 个横向排列的速记 chip。
 *
 * 简化原因(2026-07-21):原状态卡的助手/连接/会话/最近任务四行在顶部状态栏
 * 已重复展示,eyebrow"个人任务助手"信息冗余,故一并移除。本组件现在只负责
 * 引导内容,props 从 5 项收敛为 1 项(仅 onInsertPrompt)。
 *
 * 输入框已统一到底部 Composer(ChatArea 层渲染),本组件不含输入逻辑。
 */

import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { QUICK_PROMPTS } from './constants';

export interface EmptyStateProps {
  onInsertPrompt: (text: string) => void;
}

export function EmptyState({ onInsertPrompt }: EmptyStateProps) {
  return (
    <div className="empty-state flex w-full max-w-3xl flex-col items-center gap-10 px-6 py-16">
      <h1 className="hero-title-2xl text-balance text-center font-semibold tracking-tight text-foreground">
        今天想让我帮你做什么？
      </h1>
      <p className="max-w-xl text-center text-sm leading-relaxed text-muted-foreground">
        Nexus 会在后台理解任务、选择模型、整理上下文和记录必要信息。
        你只需要把事情交给它。
      </p>
      <div className="prompt-row flex flex-wrap items-center justify-center gap-2">
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
    </div>
  );
}
