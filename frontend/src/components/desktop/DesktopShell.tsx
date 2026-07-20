import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../../store';
import { useBootstrap } from './hooks/useBootstrap';
import { useDarkModeRoot } from './hooks/useDarkModeRoot';
import { useGlobalShortcuts, focusElement, closeTopModal } from './hooks/useGlobalShortcuts';
import { useChannelStatusPolling } from '../../hooks/useChannelStatusPolling';
import { useConversationCrud } from './hooks/useConversationCrud';
import { PreferencesModal } from './PreferencesModal';
import { ShellLayout } from './ShellLayout';
import { CommandPalette } from './CommandPalette';
import { WeChatModal } from './WeChatModal';
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
  // 偏好设置
  onOpenPreferences: () => void;
  // 微信通道弹窗
  onOpenWechat: () => void;
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [wechatOpen, setWechatOpen] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  const navigate = useNavigate();

  const modelName = useStore((state) => state.modelName);

  const handleNewTask = useCallback((): void => {
    onNewTask();
    navigate('/chat');
  }, [onNewTask, navigate]);

  const handleOpenPreferences = useCallback(() => setPreferencesOpen(true), []);
  const handleClosePreferences = useCallback(() => setPreferencesOpen(false), []);
  const handleOpenWechat = useCallback(() => setWechatOpen(true), []);
  const handleCloseWechat = useCallback(() => setWechatOpen(false), []);

  // 监听来自 ModelSelector"配置自定义模型"按钮的自定义事件
  useEffect(() => {
    const handler = (): void => setPreferencesOpen(true);
    window.addEventListener('nexus:open-preferences', handler);
    return () => window.removeEventListener('nexus:open-preferences', handler);
  }, []);

  // 监听顶栏 ⌘K 入口按钮触发的命令面板打开事件
  useEffect(() => {
    const handler = (): void => setPaletteOpen(true);
    window.addEventListener('nexus:open-command-palette', handler);
    return () => window.removeEventListener('nexus:open-command-palette', handler);
  }, []);

  useGlobalShortcuts({
    onNewTask: handleNewTask,
    onFocusSearch: () => setPaletteOpen(true),
    onFocusComposer: () => focusElement('.composer-textarea'),
    onCloseModal: () => closeTopModal(),
  });

  // useMemo 必须在 early return 之前调用(React Hooks 规则)
  const shellCtx = useMemo<DesktopShellContext>(
    () => ({
      conversations,
      currentConversationId,
      onSelectConversation,
      onDeleteConversation,
      onNewTask: handleNewTask,
      modelName,
      wsConnected,
      wechatConnected,
      onConnectedChange: setWsConnected,
      onSessionCreated,
      resetCounter,
      isBootstrapping,
      isModelConfigured,
      setModelConfigured,
      onOpenPreferences: handleOpenPreferences,
      onOpenWechat: handleOpenWechat,
    }),
    [
      conversations, currentConversationId, onSelectConversation, onDeleteConversation,
      handleNewTask, modelName, wsConnected, wechatConnected, onSessionCreated,
      resetCounter, isBootstrapping, isModelConfigured, handleOpenPreferences, handleOpenWechat,
    ],
  );

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

  return (
    <>
      <ShellLayout shellCtx={shellCtx} />
      <PreferencesModal
        open={preferencesOpen}
        onClose={handleClosePreferences}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNewTask={handleNewTask}
        onOpenPreferences={handleOpenPreferences}
        onOpenWechat={handleOpenWechat}
        conversations={conversations}
        onSelectConversation={onSelectConversation}
      />
      <WeChatModal open={wechatOpen} onClose={handleCloseWechat} />
    </>
  );
}
