/**
 * PreferencesDrawer - 设置 + 微信通道合并右侧抽屉(第十三轮 2026-07-17)。
 *
 * 之前两个独立子视图(SettingsView / WechatAssistantView)经 DesktopShell 的
 * view state 全屏路由,问题:
 *   - 入口分散(sidebar 顶齿轮 + 底微信按钮都进 main 区全屏)
 *   - 全屏切走时 ChatArea 卸载,上下文丢失
 *   - 用户在子视图时 sidebar 会话列表点了不能跳转
 *
 * 主流做法(Claude Desktop / Linear / Cursor):抽屉浮在主区之上,主区不卸载。
 * 关闭即恢复。Esc / 点蒙层 / 点 ✕ 三种关闭路径。
 *
 * 内部 tab 切「通用」「微信通道」两块。原 WechatAssistantView 的 ChannelViewBase
 * + ChannelInbox 继续作为 children 复用 — 它们是跟通道类型解耦的通用基类。
 */

import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';
import { useCopyText } from '../../lib/useContextMenuTrigger';
import ModelConfigModal from '../ModelConfigModal';
import { ChannelViewBase } from './channels/ChannelViewBase';
import WechatPluginModal from '../WechatPluginModal';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';

export type PreferencesTab = 'general' | 'wechat';

export interface PreferencesDrawerProps {
  open: boolean;
  initialTab?: PreferencesTab;
  onClose: () => void;
}

export function PreferencesDrawer({ open, initialTab = 'general', onClose }: PreferencesDrawerProps) {
  const [activeTab, setActiveTab] = useState<PreferencesTab>(initialTab);
  const [showModelConfig, setShowModelConfig] = useState(false);
  const [showBindModal, setShowBindModal] = useState(false);
  const drawerRef = useRef<HTMLDivElement | null>(null);

  // 抽屉打开时:activeTab 跟随 initialTab,焦点进抽屉;关闭时不动
  useEffect(() => {
    if (open) {
      setActiveTab(initialTab);
      // 下一个 tick 让 drawer 渲染完再聚焦,否则 querySelector 找不到
      const id = window.setTimeout(() => {
        const firstFocusable = drawerRef.current?.querySelector<HTMLElement>(
          'button, [tabindex]:not([tabindex="-1"]), input, select, textarea',
        );
        firstFocusable?.focus();
      }, 50);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [open, initialTab]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay preferences-drawer-overlay"
      role="presentation"
      onClick={(e) => {
        // 点蒙层自身才关闭;点抽屉内部不冒泡到这里
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside
        ref={drawerRef}
        className="preferences-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="设置与通道"
      >
        <header className="preferences-drawer-header">
          <nav className="preferences-drawer-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'general'}
              className={`preferences-tab ${activeTab === 'general' ? 'is-active' : ''}`}
              onClick={() => setActiveTab('general')}
            >
              通用
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'wechat'}
              className={`preferences-tab ${activeTab === 'wechat' ? 'is-active' : ''}`}
              onClick={() => setActiveTab('wechat')}
            >
              微信通道
            </button>
          </nav>
          <button
            type="button"
            className="preferences-drawer-close"
            onClick={onClose}
            aria-label="关闭"
            title="关闭"
          >
            ✕
          </button>
        </header>

        <div className="preferences-drawer-body">
          {activeTab === 'general' ? (
            <GeneralPanel onOpenModelConfig={() => setShowModelConfig(true)} />
          ) : (
            <WechatPanel onOpenBindModal={() => setShowBindModal(true)} />
          )}
        </div>

        <ModelConfigModal isOpen={showModelConfig} onClose={() => setShowModelConfig(false)} />
        <WechatPluginModal isOpen={showBindModal} onClose={() => setShowBindModal(false)} />
      </aside>
    </div>
  );
}

/* ===== 内部:通用 tab ===== */

interface GeneralPanelProps {
  onOpenModelConfig: () => void;
}

function GeneralPanel({ onOpenModelConfig }: GeneralPanelProps) {
  const showThinking = useStore((state) => state.showThinking);
  const setShowThinking = useStore((state) => state.setShowThinking);
  const modelName = useStore((state) => state.modelName);
  const models = useStore((state) => state.models);
  const darkMode = useStore((state) => state.darkMode);
  const setDarkMode = useStore((state) => state.setDarkMode);

  // 切换 dark mode 同步到 .nexus-desktop 元素
  const handleToggleDarkMode = () => {
    const next = !darkMode;
    setDarkMode(next);
    const root = document.querySelector('.nexus-desktop');
    if (!root) return;
    if (next) {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
  };

  // 复制触发器(沿用 SettingsView 的可访问性)
  const copyModel = useCopyText(
    () =>
      `当前模型: ${modelName || '未配置'}\n用于桌面任务和通道回复。当前共配置 ${models.length || 0} 个模型。`,
    '设置项'
  );
  const copyPrivacy = useCopyText(
    '数据与隐私: 会话、模型配置和通道状态保存在本机,敏感信息不会写入诊断日志。本机保存。',
    '设置项'
  );
  const copyThinking = useCopyText(
    () => `显示思考过程: 在回答中展示模型的中间推理摘要。${showThinking ? '已开启' : '已关闭'}`,
    '设置项'
  );
  const copyDarkMode = useCopyText(
    () => `深色模式: 桌面版支持切换浅色与深色主题,适应不同工作环境。${darkMode ? '已开启' : '已关闭'}`,
    '设置项'
  );
  const copyAdvanced = useCopyText(
    '高级设置: 诊断、本地数据目录和启动行为后续集中放在这里,默认不打扰普通使用。稍后开放。',
    '设置项'
  );

  return (
    <section className="settings-list" role="tabpanel" aria-label="通用设置">
      <div className="setting-row" onContextMenu={copyModel}>
        <div>
          <strong>当前模型</strong>
          <span>用于桌面任务和通道回复。当前共配置 {models.length || 0} 个模型。</span>
        </div>
        <button type="button" className="toggle" onClick={onOpenModelConfig}>
          {modelName || '未配置'}
        </button>
      </div>

      <div className="setting-row" onContextMenu={copyPrivacy}>
        <div>
          <strong>数据与隐私</strong>
          <span>会话、模型配置和通道状态保存在本机,敏感信息不会写入诊断日志。</span>
        </div>
        <span className="toggle is-on" aria-label="本机保存">本机保存</span>
      </div>

      <div className="setting-row" onContextMenu={copyThinking}>
        <div>
          <strong>显示思考过程</strong>
          <span>在回答中展示模型的中间推理摘要。</span>
        </div>
        <button
          type="button"
          className={`toggle ${showThinking ? 'is-on' : ''}`}
          onClick={() => setShowThinking(!showThinking)}
          aria-pressed={showThinking}
          aria-label={`显示思考过程: ${showThinking ? '已开启' : '已关闭'}`}
        >
          {showThinking ? '已开启' : '已关闭'}
        </button>
      </div>

      <div className="setting-row" onContextMenu={copyDarkMode}>
        <div>
          <strong>深色模式</strong>
          <span>桌面版支持切换浅色与深色主题,适应不同工作环境。</span>
        </div>
        <button
          type="button"
          className={`toggle ${darkMode ? 'is-on' : ''}`}
          onClick={handleToggleDarkMode}
          aria-pressed={darkMode}
          aria-label={`深色模式: ${darkMode ? '已开启' : '已关闭'}`}
        >
          {darkMode ? '已开启' : '已关闭'}
        </button>
      </div>

      <div className="setting-row" onContextMenu={copyAdvanced}>
        <div>
          <strong>高级设置</strong>
          <span>诊断、本地数据目录和启动行为后续集中放在这里,默认不打扰普通使用。</span>
        </div>
        <span className="toggle is-disabled" aria-label="稍后开放">稍后开放</span>
      </div>
    </section>
  );
}

/* ===== 内部:微信通道 tab ===== */

interface WechatPanelProps {
  onOpenBindModal: () => void;
}

function WechatPanel({ onOpenBindModal }: WechatPanelProps) {
  return (
    <section className="wechat-panel" role="tabpanel" aria-label="微信通道设置">
      <ChannelViewBase channelType="wechat">
        <div className="wechat-copy-inline">
          <div className="wechat-mark" aria-hidden="true">微</div>
          <h1>微信通道是 Nexus 的随身入口。</h1>
          <p>
            绑定后,你可以在微信里给 Nexus 发消息。桌面端负责整理上下文、保留会话和展示完整记录,
            微信端负责随时唤起。
          </p>
          <div className="wechat-benefits">
            <span>外出时直接在微信里委托任务</span>
            <span>微信任务自动回流到桌面端</span>
            <span>绑定、重连和重新扫码集中管理</span>
          </div>
          <div className="wechat-extra-actions">
            <button
              type="button"
              className="btn-primary"
              onClick={onOpenBindModal}
              onContextMenu={(e) =>
                openContextMenuAt(e, '打开微信扫码绑定弹窗(由 WechatPluginModal 渲染二维码)。', '绑定')
              }
            >
              扫码绑定 / 重新绑定
            </button>
          </div>
        </div>
      </ChannelViewBase>
    </section>
  );
}