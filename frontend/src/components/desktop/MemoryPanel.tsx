import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { useStore } from '../../store';

/**
 * 记忆面板 — 右栏"记忆" Tab 内容(2026-07-19 新增)。
 *
 * 展示用户级长期记忆(~/.nexus/AGENTS.md),由 GET /api/memory 拉取。
 * 这是 Nexus 的核心差异化能力:LLM 跨会话持久化的偏好 / 事实 / 规则。
 * 空状态 / 加载态 / 错误态均有兜底,刷新按钮重新拉取。
 */
export function MemoryPanel() {
  const memory = useStore((s) => s.memory);
  const memoryLoading = useStore((s) => s.memoryLoading);
  const memoryError = useStore((s) => s.memoryError);
  const fetchMemory = useStore((s) => s.fetchMemory);

  useEffect(() => {
    if (!memory && !memoryLoading) {
      void fetchMemory();
    }
  }, [memory, memoryLoading, fetchMemory]);

  if (memoryLoading) {
    return <div className="memory-panel-empty">加载记忆中…</div>;
  }

  if (memoryError) {
    return (
      <div className="memory-panel-empty memory-panel-error">
        <span>记忆读取失败:{memoryError}</span>
        <button type="button" onClick={() => void fetchMemory()}>
          重试
        </button>
      </div>
    );
  }

  if (!memory || !memory.exists) {
    return (
      <div className="memory-panel-empty">
        <strong>还没有长期记忆</strong>
        <span className="memory-panel-hint">
          Nexus 会在对话中自动学习你的偏好,并写入 ~/.nexus/AGENTS.md
        </span>
      </div>
    );
  }

  return (
    <div className="memory-panel">
      <div className="memory-panel-meta">
        <span className="memory-panel-path" title={memory.path}>
          ~/.nexus/AGENTS.md
        </span>
        <span className="memory-panel-stats">
          {memory.bytes} B · {memory.lines} 行
        </span>
        <button
          type="button"
          className="memory-panel-refresh"
          onClick={() => void fetchMemory()}
        >
          刷新
        </button>
      </div>
      <div className="memory-panel-body">
        <ReactMarkdown>{memory.content}</ReactMarkdown>
      </div>
    </div>
  );
}
