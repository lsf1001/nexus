/**
 * 底栏状态条 — WorkBuddy 极简 IDE 风格。
 *
 * 设计：20px 高单行，WorkBuddy IDE 状态条风格（等宽数字 / 连接点 / 极简文本）。
 * 钉在 chat-area-wrap 底部，主对话区 flex grow 占满剩余高度。
 *
 * 显示字段：
 *   - 连接状态点（online / connecting / offline 三色）
 *   - 当前 active 模型名（modelName 非空时显示，带 title 提示）
 *   - 右侧 spacer + "local" 提示
 *
 * **2026-07-21 重定位**：EmptyState 任务状态卡已砍,StatusBar 是模型 + 连接
 * 在主界面的唯一可见位置。**2026-07-23 #2**：模型名已在此处显示。暂不显示
 * token 计数（input_tokens / output_tokens）—— 后端未下发,留待接入。
 */
import { useStore } from '../../store';

export interface StatusBarProps {
  /** WS 连接状态(DesktopShell 持有) */
  wsConnected: boolean;
  /** 模型是否已配置(从 bootstrap 拿) */
  modelConfigured: boolean;
}

function resolveConnectionLabel(wsConnected: boolean, modelConfigured: boolean): {
  className: string;
  text: string;
} {
  if (wsConnected) return { className: 'is-online', text: 'online' };
  if (modelConfigured) return { className: 'is-connecting', text: 'connecting' };
  return { className: 'is-offline', text: 'offline' };
}

export function StatusBar({ wsConnected, modelConfigured }: StatusBarProps) {
  // 2026-07-23 #2:StatusBar 是模型 + 连接在主界面的唯一可见位置(2026-07-21 决策),
  // 显示当前 active model 名。modelName 变化时组件重渲染展示新值。
  const modelName = useStore((state) => state.modelName);
  const { className, text } = resolveConnectionLabel(wsConnected, modelConfigured);

  return (
    <footer className="status-bar" aria-label="状态栏">
      <span className="status-bar-item">
        <span className={`status-bar-dot ${className}`} />
        {text}
      </span>
      {modelName && (
        <span className="status-bar-item" title={`当前模型: ${modelName}`}>
          {modelName}
        </span>
      )}
      <span className="status-bar-spacer" />
      <span className="status-bar-item" title="无账户 · 本地运行">
        local
      </span>
    </footer>
  );
}
