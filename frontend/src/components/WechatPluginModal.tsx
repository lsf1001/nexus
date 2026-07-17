import { useCallback, useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { apiFetch, getApiBase } from '../lib/api';

interface WechatPluginModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (accountId: string) => void;
}

type Step = 'idle' | 'loading' | 'qr' | 'scanning' | 'success' | 'error';

interface BindStatus {
  bound: boolean;
  account_id?: string;
  status?: string;
  need_rescan?: boolean;
}

interface QRResult {
  qrcode_url: string;
  qrcode: string;
  session_key: string;
}

export function WechatPluginModal({ isOpen, onClose, onSuccess }: WechatPluginModalProps) {
  const [step, setStep] = useState<Step>('idle');
  const [qrData, setQrData] = useState<QRResult | null>(null);
  const [error, setError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [bindStatus, setBindStatus] = useState<BindStatus | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const apiUrl = `${getApiBase()}/api`;

  useEffect(() => {
    if (!isOpen) {
      setStep('idle');
      setQrData(null);
      setError('');
      setStatusMessage('');
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      return;
    }

    // 检查绑定状态
    setStep('loading');
    apiFetch(`${apiUrl}/channels/wechat/bind`)
      .then(res => res.json())
      .then((data: BindStatus) => {
        setBindStatus(data);
        if (data.bound) {
          setStep('success');
        } else if (data.need_rescan) {
          setStep('idle');
        } else {
          setStep('idle');
        }
      })
      .catch(() => {
        setStep('idle');
      });
  }, [apiUrl, isOpen]);

  // 轮询绑定状态：scanning 时启用，离开时自动清理
  useEffect(() => {
    if (step !== 'scanning' || !qrData?.session_key) return;
    const sessionKey = qrData.session_key;
    const timer = window.setInterval(async () => {
      try {
        const res = await apiFetch(`${apiUrl}/channels/wechat/status/${sessionKey}?timeout_ms=5000`);
        const status = await res.json();
        if (status.connected) {
          setStatusMessage('绑定成功！');
          setStep('success');
          onSuccess?.(status.account_id);
        } else if (status.message === 'QR code expired, please get a new one') {
          setError('二维码已过期，请重新获取');
          setStep('error');
        }
      } catch (e) {
        console.error('Poll error:', e);
      }
    }, 2000);
    pollTimerRef.current = timer;
    return () => {
      window.clearInterval(timer);
      pollTimerRef.current = null;
    };
  }, [step, qrData?.session_key, apiUrl, onSuccess]);

  // 绘制二维码
  //
  // WHY 静态 import QRCode(vs 原来动态载入 qrcode 的形式):
  // DMG 1.1.0 (2026-07-15 build) 装到 /Applications 后,modal 弹出 → 调
  // /api/channels/wechat/qr → 200 OK → canvas 空白。诊断:qrcode 包有
  // `browser` 入口字段,vite code-split 把它打成 `browser-xxx.js` 独立
  // chunk,运行时 webview 通过 `asset://` 协议动态加载该 chunk 路径解析失败,
  // mod.toCanvas 永远 undefined → canvas 静默不渲染。
  // 改静态 import → qrcode 23KB 全打主 bundle → 0 dynamic chunk → 100% 可靠。
  useEffect(() => {
    if (qrData?.qrcode_url && canvasRef.current) {
      QRCode.toCanvas(canvasRef.current, qrData.qrcode_url, {
        width: 200,
        margin: 1,
      }).catch(console.error);
    }
  }, [qrData]);

  // 开始获取二维码
  const handleGetQR = async () => {
    setStep('qr');
    setError('');
    try {
      const res = await apiFetch(`${apiUrl}/channels/wechat/qr`, { method: 'POST' });
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        setStep('error');
        return;
      }

      setQrData(data);
      setStatusMessage('请使用微信扫描二维码');
      setStep('scanning');
      // 轮询由下面 useEffect 接管
    } catch {
      setError('获取二维码失败');
      setStep('error');
    }
  };

  // 关闭弹窗
  const handleClose = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleClose, isOpen]);

  // 重新获取二维码
  const handleRetry = () => {
    setStep('idle');
    setQrData(null);
    setError('');
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={handleClose}>
      <div className="bg-white rounded-2xl w-[400px] max-h-[90vh] overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* 头部 */}
        <div className="bg-gradient-to-r from-gray-900 to-gray-800 px-5 py-4 flex items-center justify-between">
          <h3 className="text-white font-semibold text-base flex items-center gap-2">
            <span className="text-xl">📱</span> 微信插件
          </h3>
          <button onClick={handleClose} className="text-white/70 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 内容 */}
        <div className="p-6">
          {step === 'loading' && (
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-gray-100 flex items-center justify-center">
                <span className="text-4xl animate-spin">⏳</span>
              </div>
              <p className="text-gray-500 text-sm">检查绑定状态...</p>
            </div>
          )}

          {step === 'idle' && (
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-gray-100 flex items-center justify-center">
                <span className="text-4xl">💬</span>
              </div>
              <p className="text-gray-500 text-sm mb-6">
                绑定微信后，可以通过微信接收和发送消息
              </p>
              <button
                onClick={handleGetQR}
                className="w-full py-3 bg-gray-900 hover:bg-gray-800 text-white rounded-xl font-medium transition-colors"
              >
                绑定微信
              </button>
            </div>
          )}

          {(step === 'qr' || step === 'scanning') && (
            <div className="text-center">
              <p className="text-gray-500 text-sm mb-4">{statusMessage}</p>
              <div className="w-52 h-52 mx-auto mb-4 bg-white rounded-xl p-2 shadow-inner">
                <canvas ref={canvasRef} className="w-full h-full" />
              </div>
              <div className="flex items-center justify-center gap-2 text-sm text-gray-400">
                <div className="w-2 h-2 rounded-full bg-gray-900 animate-pulse" />
                <span>等待扫码...</span>
              </div>
            </div>
          )}

          {step === 'success' && (
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-gray-100 flex items-center justify-center">
                <span className="text-4xl">✅</span>
              </div>
              <p className="text-gray-900 font-medium mb-2">已绑定</p>
              {bindStatus?.account_id && (
                <p className="text-gray-400 text-xs mb-4">
                  账号: {bindStatus.account_id.slice(0, 12)}...
                </p>
              )}
              <p className="text-gray-500 text-sm mb-4">
                现在可以通过微信与 Nexus 聊天了
              </p>
              <div className="space-y-2">
                <button
                  onClick={handleClose}
                  className="w-full py-3 bg-gray-900 hover:bg-gray-800 text-white rounded-xl font-medium transition-colors"
                >
                  完成
                </button>
                <button
                  onClick={handleGetQR}
                  className="w-full py-2 text-gray-500 text-sm hover:text-gray-900 transition-colors"
                >
                  重新绑定新账号
                </button>
              </div>
            </div>
          )}

          {step === 'error' && (
            <div className="text-center">
              <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-[#ffebee] flex items-center justify-center">
                <span className="text-4xl">❌</span>
              </div>
              <p className="text-[#c62828] font-medium mb-2">出错了</p>
              <p className="text-gray-500 text-sm mb-6">{error}</p>
              <button
                onClick={handleRetry}
                className="w-full py-3 bg-gray-900 hover:bg-gray-800 text-white rounded-xl font-medium transition-colors"
              >
                重试
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default WechatPluginModal;
