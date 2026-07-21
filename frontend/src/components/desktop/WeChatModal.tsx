import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteWechatBind,
  fetchChannels,
  fetchWechatBindStatus,
  fetchWechatQr,
  fetchWechatQrStatus,
  postWechatBind,
  type ChannelInfo,
  type WechatQrResponse,
} from '../../lib/api';

export interface WeChatModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 微信通道弹窗 — 扫码登录 + 绑定状态 + 通道列表(2026-07-19)。
 *
 * 真实链路:
 *   - POST /api/channels/wechat/qr → 拿到 qrcode_url + session_key
 *   - 轮询 GET /api/channels/wechat/status/{session_key} 直到 connected
 *   - 登录成功后 POST /api/channels/wechat/bind 真正建立通道
 * 全为后端既有接口,无假控件。
 */
export function WeChatModal({ open, onClose }: WeChatModalProps) {
  const [qr, setQr] = useState<WechatQrResponse | null>(null);
  const [bound, setBound] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadChannels = useCallback(async () => {
    try {
      setChannels(await fetchChannels());
    } catch {
      /* 非关键 */
    }
  }, []);

  const refreshBind = useCallback(async () => {
    try {
      const st = await fetchWechatBindStatus();
      setBound(st.bound);
    } catch {
      setBound(false);
    }
  }, []);

  const startPoll = useCallback(
    (sessionKey: string) => {
      stopPoll();
      setStatusText('等待扫码…');
      pollRef.current = window.setInterval(async () => {
        try {
          const st = await fetchWechatQrStatus(sessionKey, 8000);
          const connected = st.connected === true;
          if (connected) {
            stopPoll();
            setStatusText('扫码成功,正在建立通道…');
            await postWechatBind();
            setBound(true);
            setStatusText('微信已连接');
            setQr(null);
            void loadChannels();
          } else if (st.status === 'expired' || String(st.message ?? '').includes('expired')) {
            stopPoll();
            setStatusText('二维码已过期,请重新获取');
          }
        } catch {
          /* 继续轮询 */
        }
      }, 3000);
    },
    [stopPoll, loadChannels],
  );

  const handleGetQr = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchWechatQr();
      if (data.success === false && data.error) {
        setError(data.error);
        return;
      }
      if (!data.session_key) {
        setError('未返回会话密钥');
        return;
      }
      setQr(data);
      startPoll(data.session_key);
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取二维码失败');
    } finally {
      setLoading(false);
    }
  }, [startPoll]);

  const handleUnbind = useCallback(async () => {
    stopPoll();
    await deleteWechatBind().catch(() => undefined);
    setBound(false);
    setQr(null);
    setStatusText('');
    void refreshBind();
    void loadChannels();
  }, [stopPoll, refreshBind, loadChannels]);

  useEffect(() => {
    if (open) {
      void refreshBind();
      void loadChannels();
      if (!bound) void handleGetQr();
    }
    return stopPoll;
  }, [open, bound, refreshBind, loadChannels, handleGetQr, stopPoll]);

  if (!open) return null;

  return (
    <div className="wechat-plugin-modal-overlay" onClick={onClose} role="presentation">
      <div
        className="wechat-modal"
        role="dialog"
        aria-label="微信通道"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="wechat-modal-head">
          <strong>微信通道</strong>
          <button type="button" className="modal-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="wechat-modal-body">
          <div className="wechat-qr-area">
            {bound ? (
              <div className="wechat-connected">
                <span className="wechat-dot on" />
                微信已连接
                <button type="button" className="wechat-unbind" onClick={handleUnbind}>
                  解除绑定
                </button>
              </div>
            ) : qr?.qrcode_url ? (
              <img className="wechat-qr" src={qr.qrcode_url} alt="微信登录二维码" />
            ) : qr?.qrcode ? (
              <pre className="wechat-qr-text">{qr.qrcode}</pre>
            ) : (
              <div className="wechat-qr-placeholder">
                {error ? <span className="wechat-error">{error}</span> : '准备二维码…'}
              </div>
            )}
          </div>

          <div className="wechat-status">
            <p>{statusText || (bound ? '通道运行中' : '使用微信扫一扫上方二维码登录')}</p>
            {!bound && !qr && !loading && (
              <button type="button" className="wechat-get-qr" onClick={handleGetQr}>
                获取二维码
              </button>
            )}
            {!bound && qr && (
              <button type="button" className="wechat-get-qr" onClick={handleGetQr}>
                刷新二维码
              </button>
            )}
          </div>

          {channels.length > 0 && (
            <div className="wechat-channels">
              <div className="wechat-channels-title">通道状态</div>
              <ul>
                {channels.map((c) => (
                  <li key={c.id} className="wechat-channel-item">
                    <span>{c.type}</span>
                    <span className={`wechat-channel-state ${c.status}`}>{c.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
