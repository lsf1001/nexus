import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useBootstrap } from './hooks/useBootstrap';
import { useDarkModeRoot } from './hooks/useDarkModeRoot';
import { useGlobalShortcuts, focusElement, closeTopModal } from './hooks/useGlobalShortcuts';
import { useChannelStatusPolling } from '../../hooks/useChannelStatusPolling';
import { useConversationCrud } from './hooks/useConversationCrud';
import { PreferencesModal, type PreferencesTab } from './PreferencesModal';
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
 * 之前 506 行的 8-职责单文件已拆为:
 *   - useBootstrap(模型配置检查 + 活跃模型名注入,首屏 RTT 减半)
 *   - useDarkModeRoot / useChannelStatusPolling
 *   - useConversationCrud(SELECT/DELETE/NEW race-guard + resetCounter)
 *   - ShellLayout(主结构 + 视图路由)
 *   - Sidebar(右侧栏 + 右键菜单)
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
  const [preferencesTab, setPreferencesTab] = useState<PreferencesTab>('general');
  const [wsConnected, setWsConnected] = useState(false);

  // 关键:useBootstrap 是 async 的,首次 render 时 initialView='setup',
  // 用 useState 同步 init 会导致 reload 后永远停在 setup。
  // 改用 effect 跟随 initialView 变化同步 view —— **但仅在 bootstrap 期间
  // 同步一次**,bootstrap 结束后不再覆盖用户手动导航(防 race:
  // 用户在 bootstrap 期间点 wechat/settings,bootstrap 完成瞬间被抢回去)。
  const hasAppliedInitial = useRef(false);
  useEffect(() => {
    if (hasAppliedInitial.current) return;
    // bootstrap 期间 'setup' 不会变,等到首次拿到真实 initialView (chat|setup)
    // 才同步一次,之后用户导航完全自由。
    if (isBootstrapping) return;
    setView(initialView);
    hasAppliedInitial.current = true;
  }, [initialView, isBootstrapping]);

  const modelName = useStore((state) => state.modelName);

  const handleNewTask = (): void => {
    onNewTask();
    setView('chat');
  };

  /**
   * 第十三轮(2026-07-17):打开偏好抽屉。
   * 侧栏顶齿轮 → 不传 tab,默认 general
   * 侧栏底微信按钮 → 传 'wechat',落点在微信通道 tab
   */
  const handleOpenPreferences = (tab: PreferencesTab = 'general'): void => {
    setPreferencesTab(tab);
    setPreferencesOpen(true);
  };

  // 第十一轮(2026-07-16)产品级打磨:全局键盘快捷键
  // 主流 agent 产品标配 — Claude Desktop / ChatGPT / Cursor 都用
  //   - Cmd+N 新建对话 → 复用 handleNewTask
  //   - Cmd+K 聚焦 sidebar 搜索框
  //   - Cmd+/ 聚焦 composer textarea
  //   - Esc 关闭最上层 modal(优先关偏好抽屉,其次其他 modal)
  useGlobalShortcuts({
    onNewTask: handleNewTask,
    onFocusSearch: () => focusElement('.sidebar-search input[type=search]'),
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
        wechatConnected={wechatConnected}
        onSelectConversation={onSelectConversation}
        onDeleteConversation={onDeleteConversation}
        onNewTask={handleNewTask}
        onOpenPreferences={handleOpenPreferences}
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