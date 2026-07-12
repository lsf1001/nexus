import { useState } from 'react';
import { apiFetch } from '../../lib/api';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';
import { secretLength } from '../../lib/secret';

interface SetupViewProps {
  onDone: () => void;
}

export function SetupView({ onDone }: SetupViewProps) {
  const [modelName, setModelName] = useState('MiniMax-M3');
  const [apiBase, setApiBase] = useState('https://api.minimaxi.com/v1');
  const [apiKey, setApiKey] = useState('');
  const [temperature, setTemperature] = useState('0.7');
  const [status, setStatus] = useState('填写 API 密钥后测试连接');
  const [isSaving, setIsSaving] = useState(false);

  /**
   * API 密钥已配置时的右键菜单文本 — **完全隐藏**,不显示尾部 4 位。
   * WHY:右键菜单由 openContextMenuAt 持久化到状态(可能进 store / 日志),
   *     屏幕共享 / 录屏时也容易泄漏明文。空态直接 "(空)";有值时
   *     显示"已设置 (N 字符)"作为状态提示,不给任何字符。
   */
  const apiKeyContextLabel = apiKey
    ? `已设置(${secretLength(apiKey)} 字符)`
    : '(空)';

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

  return (
    <section className="setup-view">
      <div
        className="setup-copy"
        onContextMenu={(e) =>
          openContextMenuAt(
            e,
            '把日常想法交给一个更安静的助手。\nNexus 会在本机管理后端、数据库和会话。你只需要配置模型，然后开始对话。',
            '介绍'
          )
        }
      >
        <span className="kicker">本地运行已就绪</span>
        <h1>把日常想法交给一个更安静的助手。</h1>
        <p>
          Nexus 会在本机管理后端、数据库和会话。你只需要配置模型，然后开始对话；
          需要移动入口时，再把微信绑定成 IM 通道。
        </p>
      </div>

      <div className="setup-card">
        <div className="card-heading">
          <div>
            <h2>连接你的模型</h2>
            <p>首版只保留必要配置，高级选项放在设置页。</p>
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
            onClick={() => setStatus('连接测试将在后续版本显示详细诊断')}
          >
            测试连接
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
    </section>
  );
}
