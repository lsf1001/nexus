import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
 * 外壳上下文:DesktopShell 组装后通过 <Outlet context> 下发给所有子路由
 * (ChatView / SetupView / 守卫)。原 `view: setup|chat` 状态枚举已被路由取代,
 * 这里改为下发 bootstrap 结果与「模型是否已配置」开关供路由守卫使用。
 */
export interface DesktopShellContext {
  // session 状态
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
  // 模型 / 连接
  modelName: string;
  wsConnected: boolean;
  wechatConnected: boolean;
  onConnectedChange: (connected: boolean) => void;
  onSessionCreated: (sessionId: string, title: string) => void;
  resetCounter: number;
  // bootstrap / 路由守卫
  isBootstrapping: boolean;
  isModelConfigured: boolean;
  setModelConfigured: (configured: boolean) => void;
}

/**
 * 桌面端外壳组合层。每个职责拆到独立 hook / 子组件,本组件只负责把它们组装起来,
 * 并通过 <Outlet context> 把外壳上下文下发给路由。视图切换由 react-router
 * (HashRouter) 驱动,不再用本地 view 枚举。
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

  // 模型是否已配置:首启用 bootstrap(initialView)判定;
  // SetupView 保存成功后由路由调用 setModelConfigured(true) 翻转为已配置。
  const [modelConfigured, setModelConfigured] = useState<boolean | null>(null);
  const isModelConfigured = modelConfigured ?? initialView === 'chat';

  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  const navigate = useNavigate();

  const modelName = useStore((state) => state.modelName);

  const handleNewTask = (): void => {
    onNewTask();
    navigate('/chat');
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

  const shellCtx: DesktopShellContext = {
    conversations,
    currentConversationId,
    onSelectConversation,
    onDeleteConversation,
    onNewTask,
    modelName,
    wsConnected,
    wechatConnected,
    onConnectedChange: setWsConnected,
    onSessionCreated,
    resetCounter,
    isBootstrapping,
    isModelConfigured,
    setModelConfigured,
  };

  return (
    <>
      <ShellLayout shellCtx={shellCtx} />
      <PreferencesModal
        open={preferencesOpen}
        onClose={() => setPreferencesOpen(false)}
      />
    </>
  );
}
