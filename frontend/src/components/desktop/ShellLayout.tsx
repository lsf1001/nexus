import { Outlet } from 'react-router-dom';
import { ContextMenuHost } from './ContextMenuHost';
import { Sidebar } from './Sidebar';
import { ToastHost } from '../ToastHost';
import { ArtifactsPanel } from './ArtifactsPanel';
import type { DesktopShellContext } from './DesktopShell';

export interface ShellLayoutProps {
  /** DesktopShell 组装好的外壳上下文,通过 <Outlet context> 下发给子路由。 */
  shellCtx: DesktopShellContext;
}

/**
 * 桌面端布局骨架:'.nexus-desktop' 根(含 data-theme,供 e2e / 深色模式选择器)
 * 是三列 CSS grid —— 左 `Sidebar`(264px)| 中 `<main>` 路由出口(ChatArea /
 * ChatView)| 右 `ArtifactsPanel`(auto,有 artifact 时出现,否则塌缩为 0 宽)。
 *
 * 右列由 `ArtifactsPanel` 自身控制显隐:无 artifact 时返回 null,grid 第 3 轨
 * 因为没有 grid item 自动塌缩为 0,`.chat-area`(位于中列 1fr)保持全宽,不影响
 * e2e 选择器契约(`.sidebar` / `.chat-area` / `.nexus-desktop`)。
 *
 * 视图内容由 react-router 子路由渲染(`.main` 内 <Outlet>),不再由本地 view
 * 枚举切换。
 */
export function ShellLayout({ shellCtx }: ShellLayoutProps) {
  return (
    <div className="nexus-desktop">
      <Sidebar
        conversations={shellCtx.conversations}
        currentConversationId={shellCtx.currentConversationId}
        onSelectConversation={shellCtx.onSelectConversation}
        onDeleteConversation={shellCtx.onDeleteConversation}
        onNewTask={shellCtx.onNewTask}
      />

      <main className="main">
        <Outlet context={shellCtx} />
      </main>

      <ArtifactsPanel />

      <ContextMenuHost />
      <ToastHost />
    </div>
  );
}
