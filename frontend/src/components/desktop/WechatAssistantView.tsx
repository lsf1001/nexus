/**
 * WechatAssistantView - 微信通道视图(C5 重构后的薄壳)。
 *
 * 之前 200+ 行的"bind 轮询 + 收件箱 + 状态卡"已全部下沉到:
 *   - ChannelViewBase: 绑卡 + 解绑 + 通用 children 槽
 *   - ChannelInbox: 按 channelType 分桶的收件箱
 *   - useChannelStatusPolling: 通用状态轮询 hook
 *
 * 本组件只剩 WeChat 特有 UI(品牌头部/状态文案/绑定弹窗)作为 children。
 * 未来加 Telegram/Feishu 通道:新建一个 TelegramView 薄壳即可。
 */

import { useState } from 'react';
import { ChannelViewBase } from './channels/ChannelViewBase';
import WechatPluginModal from '../WechatPluginModal';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';

export interface WechatAssistantViewProps {
  onBack?: () => void;
}

export function WechatAssistantView({ onBack }: WechatAssistantViewProps = {}) {
  const [showBindModal, setShowBindModal] = useState(false);

  return (
    <ChannelViewBase channelType="wechat">
      <section className="wechat-view">
        {onBack && (
          <div className="wechat-header">
            <button
              type="button"
              className="back-btn"
              onClick={onBack}
              aria-label="返回聊天"
              title="返回聊天"
            >
              ← 返回聊天
            </button>
          </div>
        )}
        <div className="wechat-copy">
          <div className="wechat-mark">微</div>
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
        </div>

        <div className="wechat-extra-actions">
          <button
            type="button"
            className="btn-primary"
            onClick={() => setShowBindModal(true)}
            onContextMenu={(e) =>
              openContextMenuAt(e, '打开微信扫码绑定弹窗(由 WechatPluginModal 渲染二维码)。', '绑定')
            }
          >
            扫码绑定 / 重新绑定
          </button>
        </div>
      </section>

      <WechatPluginModal isOpen={showBindModal} onClose={() => setShowBindModal(false)} />
    </ChannelViewBase>
  );
}
