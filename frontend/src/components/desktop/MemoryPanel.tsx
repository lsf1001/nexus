import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useStore } from '../../store';
import { useToastStore } from '../../store/useToast';

/**
 * 记忆面板 — 右栏"记忆" Tab 内容(2026-07-19 新增)。
 *
 * 展示用户级长期记忆(~/.nexus/AGENTS.md),由 GET /api/memory 拉取。
 * 这是 Nexus 的核心差异化能力:LLM 跨会话持久化的偏好 / 事实 / 规则。
 * 空状态 / 加载态 / 错误态均有兜底,刷新按钮重新拉取。
 *
 * #14 记忆面板增强(2026-07-23):新增 3 个操作按钮 —
 *   1. 复制路径(到剪贴板,用户在终端 cd 进去)
 *   2. 复制内容(整段 markdown 到剪贴板,直接粘贴到任何编辑器)
 *   3. 下载 .md(浏览器 fallback:用 Blob + anchor 触发下载;桌面端 Tauri's
 *      invoke('reveal_in_finder') 需要后端配合,本期 YAGNI,纯前端即可)
 *   4. 刷新 loading 改为组件内 useState(不复用 store memoryLoading,后者
 *      仅初次挂载用)— 刷新期间按钮 disabled + spinner。
 */
export function MemoryPanel() {
  const memory = useStore((s) => s.memory);
  const memoryLoading = useStore((s) => s.memoryLoading);
  const memoryError = useStore((s) => s.memoryError);
  const fetchMemory = useStore((s) => s.fetchMemory);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    if (!memory && !memoryLoading) {
      void fetchMemory();
    }
  }, [memory, memoryLoading, fetchMemory]);

  const handleRefresh = async (): Promise<void> => {
    setIsRefreshing(true);
    try {
      await fetchMemory();
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleCopyPath = async (): Promise<void> => {
    if (!memory) return;
    try {
      await navigator.clipboard.writeText(memory.path);
      useToastStore.getState().push('info', '路径已复制', 1500);
    } catch {
      useToastStore.getState().push('info', '复制失败,请手动选择', 2000);
    }
  };

  const handleCopyContent = async (): Promise<void> => {
    if (!memory) return;
    try {
      await navigator.clipboard.writeText(memory.content);
      useToastStore.getState().push('info', '内容已复制', 1500);
    } catch {
      useToastStore.getState().push('info', '复制失败,请手动选择', 2000);
    }
  };

  const handleDownload = (): void => {
    if (!memory) return;
    try {
      const blob = new Blob([memory.content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'AGENTS.md';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      useToastStore.getState().push('info', '已下载 AGENTS.md', 1500);
    } catch {
      useToastStore.getState().push('info', '下载失败', 2000);
    }
  };

  if (memoryLoading && !memory) {
    return <div className="memory-panel-empty">加载记忆中…</div>;
  }

  if (memoryError && !memory) {
    return (
      <div className="memory-panel-empty memory-panel-error">
        <span>记忆读取失败:{memoryError}</span>
        <button type="button" onClick={() => void handleRefresh()} disabled={isRefreshing}>
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
      </div>
      <div className="memory-panel-actions">
        <button
          type="button"
          className="memory-panel-action"
          onClick={() => void handleCopyPath()}
          disabled={isRefreshing}
          data-testid="memory-copy-path"
          title="复制 ~/.nexus/AGENTS.md 路径"
        >
          复制路径
        </button>
        <button
          type="button"
          className="memory-panel-action"
          onClick={() => void handleCopyContent()}
          disabled={isRefreshing}
          data-testid="memory-copy-content"
          title="复制全部 markdown 内容"
        >
          复制内容
        </button>
        <button
          type="button"
          className="memory-panel-action"
          onClick={handleDownload}
          disabled={isRefreshing}
          data-testid="memory-download"
          title="下载为 AGENTS.md"
        >
          下载
        </button>
        <button
          type="button"
          className="memory-panel-action memory-panel-refresh"
          onClick={() => void handleRefresh()}
          disabled={isRefreshing}
          data-testid="memory-refresh"
          title="重新读取 ~/.nexus/AGENTS.md"
        >
          {isRefreshing ? '刷新中…' : '刷新'}
        </button>
      </div>
      <div className="memory-panel-body">
        <ReactMarkdown>{memory.content}</ReactMarkdown>
      </div>
    </div>
  );
}
