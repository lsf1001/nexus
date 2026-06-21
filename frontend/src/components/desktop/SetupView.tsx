import { useState } from 'react';
import { apiFetch } from '../../lib/api';
import { openContextMenuAt } from '../../lib/useContextMenuTrigger';

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

  const saveModel = async () => {
    setIsSaving(true);
    setStatus('正在保存模型配置...');

    try {
      await apiFetch('/api/models/default', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: modelName,
          api_key: apiKey,
          api_base: apiBase,
          temperature: Number.parseFloat(temperature) || 0.7,
        }),
      });
      setStatus('配置已保存，可以开始使用');
      onDone();
    } catch {
      setStatus('保存失败，请检查后端状态和 API 密钥');
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
            onContextMenu={(e) => openContextMenuAt(e, apiKey ? '••••••' + apiKey.slice(-4) : '(空)', 'API 密钥')}
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
