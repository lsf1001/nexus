import { useState } from 'react';
import { useStore } from '../../store/useStore';
import { useCopyText } from '../../lib/useContextMenuTrigger';
import ModelConfigModal from '../ModelConfigModal';

export interface SettingsViewProps {
  onBack?: () => void;
}

export function SettingsView({ onBack }: SettingsViewProps = {}) {
  const showThinking = useStore((state) => state.showThinking);
  const setShowThinking = useStore((state) => state.setShowThinking);
  const modelName = useStore((state) => state.modelName);
  const models = useStore((state) => state.models);
  const darkMode = useStore((state) => state.darkMode);
  const setDarkMode = useStore((state) => state.setDarkMode);
  const [showModelConfig, setShowModelConfig] = useState(false);

  // 不再维护 local models:从 useStore.models 读,modal 切完会通过
  // setModels 写进 store,这里自动 re-render。useBootstrap 已经把首个
  // active model 写进 modelName,ModelConfigModal 切完也会再同步一次。
  // 旧实现 useState + useEffect([]) 只拉一次,modal 切完 SettingsView
  // 的 models.length 永远停在初值,user 看到「共配置 N 个」不变。

  // 切换 dark mode 时同步到 .nexus-desktop 元素（CSS 选择器作用域）
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

  // 各行复制触发器 —— 复制整行可读文字（标题 + 描述 + 当前值）
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
    <section className="settings-view">
      <div className="settings-header">
        {onBack && (
          <button
            type="button"
            className="back-btn"
            onClick={onBack}
            aria-label="返回聊天"
            title="返回聊天"
          >
            ← 返回聊天
          </button>
        )}
      </div>
      <div className="settings-list">
        <div className="setting-row" onContextMenu={copyModel}>
          <div>
            <strong>当前模型</strong>
            <span>用于桌面任务和通道回复。当前共配置 {models.length || 0} 个模型。</span>
          </div>
          <button
            type="button"
            className="toggle"
            onClick={() => setShowModelConfig(true)}
          >
            {modelName || '未配置'}
          </button>
        </div>

        <div className="setting-row" onContextMenu={copyPrivacy}>
          <div>
            <strong>数据与隐私</strong>
            <span>会话、模型配置和通道状态保存在本机，敏感信息不会写入诊断日志。</span>
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
          >
            {showThinking ? '已开启' : '已关闭'}
          </button>
        </div>

        <div className="setting-row" onContextMenu={copyDarkMode}>
          <div>
            <strong>深色模式</strong>
            <span>桌面版支持切换浅色与深色主题，适应不同工作环境。</span>
          </div>
          <button
            type="button"
            className={`toggle ${darkMode ? 'is-on' : ''}`}
            onClick={handleToggleDarkMode}
          >
            {darkMode ? '已开启' : '已关闭'}
          </button>
        </div>

        <div className="setting-row" onContextMenu={copyAdvanced}>
          <div>
            <strong>高级设置</strong>
            <span>诊断、本地数据目录和启动行为后续集中放在这里，默认不打扰普通使用。</span>
          </div>
          <span className="toggle is-disabled" aria-label="稍后开放">稍后开放</span>
        </div>
      </div>

      <ModelConfigModal isOpen={showModelConfig} onClose={() => setShowModelConfig(false)} />
    </section>
  );
}
