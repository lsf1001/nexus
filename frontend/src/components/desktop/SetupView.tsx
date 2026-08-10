import { useState } from 'react';
import { apiFetch } from '../../lib/api';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { secretLength } from '../../lib/secret';
import { DEFAULT_MODEL, DEFAULT_API_BASE } from '../../lib/config';

interface SetupViewProps {
  onDone: () => void;
}

export function SetupView({ onDone }: SetupViewProps) {
  const [modelName, setModelName] = useState(DEFAULT_MODEL);
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [apiKey, setApiKey] = useState('');
  const [temperature, setTemperature] = useState('0.7');
  const [status, setStatus] = useState('填写 API 密钥后测试连接');
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);

  /**
   * API 密钥已配置时的右键菜单文本 — **完全隐藏**,不显示尾部 4 位。
   * WHY:右键菜单由 openContextMenuAt 持久化到状态(可能进 store / 日志),
   *     屏幕共享 / 录屏时也容易泄漏明文。空态直接 "(空)";有值时
   *     显示"已设置 (N 字符)"作为状态提示,不给任何字符。
   */
  const apiKeyContextLabel = apiKey
    ? `已设置(${secretLength(apiKey)} 字符)`
    : '(空)';

  const testConnection = async () => {
    setIsTesting(true);
    setStatus('正在测试连接...');
    try {
      const response = await apiFetch('/api/models/default/test', { method: 'GET' });
      if (!response.ok) {
        // 复用 saveModel 的错误分类:401/403 鉴权、422 参数、5xx 后端故障、其它兜底。
        // WHY 只取首行 + 截断:后端 body 可能含错误码,防止把长 traceback 灌进 UI。
        const errText = (await response.text().catch(() => '')).trim();
        const reason = errText ? `: ${(errText.split('\n')[0] ?? '').slice(0, 120)}` : '';
        if (response.status === 401 || response.status === 403) {
          setStatus(`测试连接鉴权失败,请检查 API 密钥${reason}`);
        } else if (response.status === 422) {
          setStatus(`测试连接参数错误${reason}`);
        } else if (response.status >= 500) {
          setStatus(`后端服务异常(${response.status})${reason}`);
        } else {
          setStatus(`测试失败(${response.status})${reason}`);
        }
        return;
      }
      setStatus('连接测试成功 ✓');
    } catch {
      // 网络层错误(后端没起 / fetch 抛异常);不暴露详情防止泄漏内部路径。
      setStatus('连接测试失败,请检查后端状态和网络');
    } finally {
      setIsTesting(false);
    }
  };

  const saveModel = async () => {
    setIsSaving(true);
    setStatus('正在保存模型配置...');

    try {
      const response = await apiFetch('/api/models/default', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: modelName,
          api_key: apiKey,
          api_base: apiBase,
          temperature: Number.parseFloat(temperature) || 0.7,
        }),
      });
      if (!response.ok) {
        // 区分后端拒收(4xx)与后端故障(5xx),给用户更可执行的提示。
        // WHY 不直接打 response.text():401/422 的 body 含后端错误码,
        //   简单展示首行即可;空 body 也兜底。
        const errText = (await response.text().catch(() => '')).trim();
        const reason = errText ? `: ${(errText.split('\n')[0] ?? '').slice(0, 120)}` : '';
        if (response.status === 401 || response.status === 403) {
          setStatus(`鉴权失败,请检查后端 NEXUS_WS_TOKEN 配置${reason}`);
        } else if (response.status === 422) {
          setStatus(`参数被后端拒绝${reason}`);
        } else if (response.status >= 500) {
          setStatus(`后端服务异常(${response.status}),请稍后重试${reason}`);
        } else {
          setStatus(`保存失败(${response.status})${reason}`);
        }
        return;
      }
      setStatus('配置已保存,可以开始使用');
      onDone();
    } catch (_e) {
      // 网络层错误(后端没起 / CORS / fetch 抛异常);不暴露 e 详情防止泄漏内部路径。
      setStatus('保存失败,请检查后端状态和 API 密钥');
    } finally {
      setIsSaving(false);
    }
  };

  // 第八轮(2026-07-15):Claude Desktop 单层化 — 跟 ChatView / SettingsView / Wechat 同源
  //   chat-area-wrap(flex column) + 36px chat-status-bar(左标题)
  //   替代过去的 .setup-view 块级padding布局。
  //   .setup-card 仍保留作为 setup-form 容器(让 setup-card input 等选择器继续生效),
  //   而 setup-card 自身是 transparent + 无 box-shadow + 无 border,跟其它表单一致走 inline 形态。
  return (
    <div className="chat-area-wrap">
      <header className="chat-status-bar" data-tauri-drag-region>
        <span className="chat-status-topic" title="连接你的模型">
          连接你的模型
        </span>
      </header>

      <div className="setup-view">
        <div className="setup-card">
          <div className="card-heading">
            <div>
              <h2>连接你的模型</h2>
              <p>首次使用请填写一次,后续可在设置页修改。</p>
            </div>
            <span className="step-tag">1 / 1</span>
          </div>

          <label>
            模型
            <input
              value={modelName}
              onChange={(event) => setModelName(event.target.value)}
              onContextMenu={(e) => openContextMenuAt(e, modelName, '模型名')}
            />
          </label>
          <label>
            API 地址
            <input
              value={apiBase}
              onChange={(event) => setApiBase(event.target.value)}
              onContextMenu={(e) => openContextMenuAt(e, apiBase, 'API 地址')}
            />
          </label>
          <label>
            API 密钥
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              onContextMenu={(e) => openContextMenuAt(e, apiKeyContextLabel, 'API 密钥')}
            />
          </label>
          <label>
            温度参数
            <input
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
              onContextMenu={(e) => openContextMenuAt(e, temperature, '温度参数')}
            />
          </label>

          <div className={`hint ${status.includes('失败') ? 'is-error' : ''}`}>{status}</div>
          <div className="actions">
            <button
              type="button"
              className="btn-secondary"
              disabled={isTesting || isSaving}
              aria-busy={isTesting}
              onClick={testConnection}
            >
              {isTesting ? '测试中...' : '测试连接'}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={isSaving || !apiKey.trim()}
              onClick={saveModel}
            >
              开始使用
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
