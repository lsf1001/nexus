import { useEffect, useState } from 'react';
import { apiFetch } from '../../lib/api';
import { useStore } from '../../store/useStore';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import WechatPluginModal from '../WechatPluginModal';

interface WechatBindStatus {
  bound: boolean;
  account_id?: string;
  status?: string;
  need_rescan?: boolean;
}

export interface WechatAssistantViewProps {
  onBack?: () => void;
}

export function WechatAssistantView({ onBack }: WechatAssistantViewProps = {}) {
  const [showBindModal, setShowBindModal] = useState(false);
  const [bindStatus, setBindStatus] = useState<WechatBindStatus | null>(null);

  // 微信收件箱：WS 收到的 wechat_message 自动 push 进这里。
  // 主会话不再被串台污染；用户进此视图才看到完整内容。
  const wechatInbox = useStore((state) => state.wechatInbox);
  const clearWechatInbox = useStore((state) => state.clearWechatInbox);

  useEffect(() => {
    let cancelled = false;

    const loadStatus = async () => {
      try {
        const response = await apiFetch('/api/channels/wechat/bind');
        const data = await response.json() as WechatBindStatus;
        if (!cancelled) {
          setBindStatus(data);
        }
      } catch {
        if (!cancelled) {
          setBindStatus({ bound: false });
        }
      }
    };

    loadStatus();
    const timer = window.setInterval(loadStatus, 10000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // 进入微信通道视图即清空收件箱(标记已读)。
  // 之前没有这个 useEffect,用户从别处看到 Sidebar 计数后点进视图,
  // 红点不消失,体验断裂。卸载时(切到别的视图)不动数据,等下次进入再清。
  useEffect(() => {
    if (wechatInbox.length > 0) {
      clearWechatInbox();
    }
    // 故意只依赖 mount(空数组):进入即清一次,后续新到消息会在下个 mount 清
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isConnected = bindStatus?.bound && bindStatus.status === 'running';
  const statusTitle = isConnected ? '微信通道已连接' : bindStatus?.need_rescan ? '需要重新扫码' : '等待绑定';
  const statusDetail = isConnected
    ? `账号 ${bindStatus?.account_id?.slice(0, 12) ?? '已绑定'} 已连接，可直接从微信发消息给 Nexus。`
    : bindStatus?.need_rescan
      ? '上一次绑定需要重新确认，建议重新获取二维码。'
      : '你可以把微信作为移动入口，桌面端会保留完整会话和上下文。';

  return (
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
          绑定后，你可以在微信里给 Nexus 发消息。桌面端负责整理上下文、保留会话和展示完整记录，
          微信端负责随时唤起。
        </p>
        <div className="wechat-benefits">
          <span>外出时直接在微信里委托任务</span>
          <span>微信任务自动回流到桌面端</span>
          <span>绑定、重连和重新扫码集中管理</span>
        </div>
      </div>

      <div className="wechat-bind-card">
        <div
          className={`wechat-status-chip ${isConnected ? 'connected' : ''}`}
          onContextMenu={(e) =>
            openContextMenuAt(
              e,
              `微信通道 · ${statusTitle}\n${statusDetail}`,
              '状态'
            )
          }
        >
          {statusTitle}
        </div>
        <h2>绑定微信通道</h2>
        <p>{statusDetail}</p>
        <div className="wechat-status-list">
          <div
            onContextMenu={(e) =>
              openContextMenuAt(
                e,
                '移动入口 · 在外出场景里快速把任务交给 Nexus。',
                '说明'
              )
            }
          >
            <strong>移动入口</strong>
            <span>在外出场景里快速把任务交给 Nexus。</span>
          </div>
          <div
            onContextMenu={(e) =>
              openContextMenuAt(
                e,
                '会话回流 · 微信消息会自动进入桌面端会话列表。',
                '说明'
              )
            }
          >
            <strong>会话回流</strong>
            <span>微信消息会自动进入桌面端会话列表。</span>
          </div>
          <div
            onContextMenu={(e) =>
              openContextMenuAt(
                e,
                `当前状态 · ${isConnected ? '通道运行中' : '尚未建立稳定连接'}`,
                '状态'
              )
            }
          >
            <strong>当前状态</strong>
            <span>{isConnected ? '通道运行中' : '尚未建立稳定连接'}</span>
          </div>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => window.location.reload()}
          >
            刷新状态
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => setShowBindModal(true)}
          >
            {isConnected ? '重新绑定' : '开始绑定'}
          </button>
        </div>

        {wechatInbox.length > 0 && (
          <div className="wechat-inbox">
            <div className="inbox-header">
              <strong>收件箱（{wechatInbox.length}）</strong>
              <button
                type="button"
                className="btn-secondary"
                onClick={clearWechatInbox}
              >
                全部已读
              </button>
            </div>
            <ul>
              {wechatInbox.map((msg) => (
                <li
                  key={msg.id}
                  className="inbox-item"
                  onContextMenu={(e) =>
                    openContextMenuAt(
                      e,
                      `[${msg.createdAt.toLocaleString('zh-CN')}] ${msg.content}`,
                      '微信消息'
                    )
                  }
                >
                  <span className="inbox-time">
                    {msg.createdAt.toLocaleTimeString()}
                  </span>
                  <span className="inbox-content">{msg.content}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <WechatPluginModal isOpen={showBindModal} onClose={() => setShowBindModal(false)} />
    </section>
  );
}
