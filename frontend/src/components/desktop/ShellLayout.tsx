import { Outlet } from 'react-router-dom';
import { ContextMenuHost } from './ContextMenuHost';
import { Sidebar } from './Sidebar';
import { ToastHost } from '../ToastHost';
import { ArtifactsPanel } from '../Artifacts/ArtifactsPanel';
import { useStore } from '../../store';
import type { DesktopShellContext } from './DesktopShell';

export interface ShellLayoutProps {
  /** DesktopShell 组装好的外壳上下文,通过 <Outlet context> 下发给子路由。 */
  shellCtx: DesktopShellContext;
}

/**
 * 桌面端布局骨架：三列 CSS grid ——
 *   左 `Sidebar`(260px)| 中 `<main>` 路由出口(ChatArea / ChatView)| 右
 *   `<ArtifactsPanel>`(可折叠,默认折叠回退两栏)。
 *
 * 折叠态通过 `artifactsCollapsed` 切换:折叠时 Panel 内部返回 null,主
 * 区由 grid 自然铺满;展开时按 `260 + minmax(0,760) + minmax(0,1fr)`
 * 三栏布局。
 *
 * 低频入口(记忆 / 工具 / 微信 / Artifacts 折叠态入口等)由 `⌘K` 命令面板
 * 承担(快捷键 Cmd/Ctrl+K,UI 无按钮入口)。视图内容由 react-router 子路由渲染(`.main` 内 <Outlet>)。
 */
export function ShellLayout({ shellCtx }: ShellLayoutProps) {
  const collapsed = useStore((s) => s.artifactsCollapsed);

  return (
    <div className={`nexus-desktop${collapsed ? ' artifacts-collapsed' : ''}`}>
      <Sidebar
        conversations={shellCtx.conversations}
        currentConversationId={shellCtx.currentConversationId}
        onSelectConversation={shellCtx.onSelectConversation}
        onDeleteConversation={shellCtx.onDeleteConversation}
        onNewTask={shellCtx.onNewTask}
        onOpenPreferences={shellCtx.onOpenPreferences}
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