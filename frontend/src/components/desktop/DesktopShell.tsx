import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useBootstrap } from './hooks/useBootstrap';
import { useDarkModeRoot } from './hooks/useDarkModeRoot';
import { useGlobalShortcuts, focusElement, closeTopModal } from './hooks/useGlobalShortcuts';
import { useChannelStatusPolling } from '../../hooks/useChannelStatusPolling';
import { useConversationCrud } from './hooks/useConversationCrud';
import { PreferencesModal } from './PreferencesModal';
import { ShellLayout } from './ShellLayout';
import type { Conversation } from '../../types';

/**
 * 第十三轮(2026-07-17):`view` 收窄为 'setup' | 'chat'。
 * 原 'settings' / 'wechat' 已被右侧抽屉替代(Claude Desktop / Linear / Cursor 主流做法)
 * — 抽屉浮在主区之上,ChatArea 不卸载。Esc / 点蒙层 / 点 ✕ 三种关闭路径。
 */
export type DesktopView = 'setup' | 'chat';

export interface DesktopShellContext {
  // session 状态
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
  // 视图
  view: DesktopView;
  // 模型 / 连接
  modelName: string;
  wsConnected: boolean;
  wechatConnected: boolean;
}

/**
 * 桌面端外壳组合层。每个职责拆到独立 hook / 子组件,本组件只负责把它们组装起来。
 */
export function DesktopShell() {
  const { isBootstrapping, initialView } = useBootstrap();
  useDarkModeRoot(useStore((state) => state.darkMode));
  const wechatBindStatus = useChannelStatusPolling('wechat');
  const wechatConnected = !!(wechatBindStatus?.bound && wechatBindStatus.status === 'running');
  const {
    conversations,
    currentConversationId,
    resetCounter,
    onSelectConversation,
    onDeleteConversation,
    onNewTask,
    onSessionCreated,
  } = useConversationCrud();

  const [view, setView] = useState<DesktopView>(initialView);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  const hasAppliedInitial = useRef(false);
  useEffect(() => {
    if (hasAppliedInitial.current) return;
    if (isBootstrapping) return;
    setView(initialView);
    hasAppliedInitial.current = true;
  }, [initialView, isBootstrapping]);

  const modelName = useStore((state) => state.modelName);

  const handleNewTask = (): void => {
    onNewTask();
    setView('chat');
  };

  useGlobalShortcuts({
    onNewTask: handleNewTask,
    // 第十四轮:搜索 input 已删,快捷键暂 noop,待后续 Task 5 整合或重新设计
    onFocusSearch: () => {},
    onFocusComposer: () => focusElement('.composer-textarea'),
    onCloseModal: () => closeTopModal(),
  });

  if (isBootstrapping) {
    return (
      <div className="nexus-desktop nexus-desktop--loading">
        <div className="loading-copy">
          <div className="sidebar-brand-mark">N</div>
          <strong>Nexus 正在准备本地助手</strong>
          <span>检查模型配置、会话和微信状态...</span>
        </div>
      </div>
    );
  }

  const context: DesktopShellContext = {
    conversations,
    currentConversationId,
    onSelectConversation,
    onDeleteConversation,
    onNewTask,
    view,
    modelName,
    wsConnected,
    wechatConnected,
  };

  return (
    <>
      <ShellLayout
        view={view}
        onViewChange={setView}
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={onSelectConversation}
        onDeleteConversation={onDeleteConversation}
        onNewTask={handleNewTask}
        context={context}
        onConnectedChange={setWsConnected}
        onSessionCreated={onSessionCreated}
        resetCounter={resetCounter}
      />
      <PreferencesModal
        open={preferencesOpen}
        onClose={() => setPreferencesOpen(false)}
      />
    </>
  );
}
