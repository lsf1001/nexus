/**
 * ChannelViewBase - 所有通道视图的基类。
 *
 * 渲染流程:
 *   1. useChannelStatusPolling 拿 bind 状态
 *   2. 显示绑定卡片 (扫码/绑定按钮 + 状态)
 *   3. 显示 ChannelInbox (已收到的消息)
 *   4. 子组件 children 注入通道特有 UI (微信表情/Telegram inline keyboard 等)
 *
 * 复用点:任何新通道 (feishu/telegram) 只需写一个薄 wrapper 传 channelType +
 * 通道特有 children,不需要重写 bind 卡片、收件箱、WS 帧分发。
 */

import type { ReactNode } from 'react';
import { ChannelInbox } from './ChannelInbox';
import { useChannelStatusPolling } from '../../../hooks/useChannelStatusPolling';
import { apiFetch } from '../../../lib/api';
import type { ChannelType } from '../../../types';

interface ChannelViewBaseProps {
  channelType: ChannelType;
  children?: ReactNode;
}

export function ChannelViewBase({ channelType, children }: ChannelViewBaseProps) {
  const status = useChannelStatusPolling(channelType);

  const handleBind = async () => {
    try {
      const response = await apiFetch(`/api/channels/${channelType}/bind`, { method: 'POST' });
      const data = (await response.json()) as { need_rescan?: boolean };
      if (data.need_rescan) {
        window.dispatchEvent(new CustomEvent(`${channelType}:need_rescan`));
      }
    } catch (e) {
      console.error(`${channelType} bind failed:`, e);
    }
  };

  const handleUnbind = async () => {
    try {
      await apiFetch(`/api/channels/${channelType}/bind`, { method: 'DELETE' });
    } catch (e) {
      console.error(`${channelType} unbind failed:`, e);
    }
  };

  return (
    <div className={`channel-view channel-view-${channelType}`}>
      <div className="channel-bind-card">
        {status?.bound ? (
          <>
            <span>已绑定: {status.account_id}</span>
            <button type="button" onClick={handleUnbind}>解绑</button>
          </>
        ) : (
          <button type="button" onClick={handleBind}>扫码绑定 {channelType}</button>
        )}
      </div>

      <ChannelInbox channelType={channelType} />

      <div className="channel-children">{children}</div>
    </div>
  );
}
