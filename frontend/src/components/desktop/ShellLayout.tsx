import { Outlet } from 'react-router-dom';
import { ContextMenuHost } from './ContextMenuHost';
import { Sidebar } from './Sidebar';
import { ToastHost } from '../ToastHost';
import type { DesktopShellContext } from './DesktopShell';

export interface ShellLayoutProps {
  /** DesktopShell 组装好的外壳上下文,通过 <Outlet context> 下发给子路由。 */
  shellCtx: DesktopShellContext;
}

/**
 * 桌面端布局骨架:'.nexus-desktop' 根(含 data-theme,供 e2e / 深色模式选择器)
 * + Sidebar + <main> 内的路由出口。视图内容由 react-router 子路由渲染,
 * 不再由本地 view 枚举切换。
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

      <ContextMenuHost />
      <ToastHost />
    </div>
  );
}
