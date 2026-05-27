import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';

interface Model {
  id: string;
  name: string;
  api_key: string;
  api_base: string;
  temperature: number;
  is_active: boolean;
}

interface ModelConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function ModelConfigModal({ isOpen, onClose }: ModelConfigModalProps) {
  const models = useStore((s) => s.models);
  const setModels = useStore((s) => s.setModels);
  const setCurrentModelId = useStore((s) => s.setCurrentModelId);
  const setModelName = useStore((s) => s.setModelName);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    api_key: '',
    api_base: 'https://api.minimaxi.com/v1',
    temperature: 0.7,
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const apiUrl = `${window.location.protocol}//${window.location.host}/api`;

  useEffect(() => {
    if (isOpen) {
      setEditingModel(null);
      setIsCreating(false);
      setError(null);
      setFormData({
        id: '',
        name: '',
        api_key: '',
        api_base: 'https://api.minimaxi.com/v1',
        temperature: 0.7,
      });
    }
  }, [isOpen]);

  const handleCreateNew = () => {
    setIsCreating(true);
    setEditingModel(null);
    setFormData({
      id: `model-${Date.now()}`,
      name: '新模型',
      api_key: '',
      api_base: 'https://api.minimaxi.com/v1',
      temperature: 0.7,
    });
  };

  const handleEdit = (model: Model) => {
    setIsCreating(false);
    setEditingModel(model);
    setFormData({
      id: model.id,
      name: model.name,
      api_key: model.api_key || '',
      api_base: model.api_base || 'https://api.minimaxi.com/v1',
      temperature: model.temperature,
    });
  };

  const handleDelete = async (modelId: string) => {
    if (!confirm('确定要删除这个模型吗？')) return;

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/models/${modelId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        // 重新获取模型列表
        const modelsRes = await fetch(`${apiUrl}/models`);
        const modelsData = await modelsRes.json();
        setModels(modelsData);
        setEditingModel(null);
        setIsCreating(false);
      } else {
        setError(data.error || '删除失败');
      }
    } catch (err) {
      setError('删除失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSwitchModel = async (modelId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/models/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: modelId }),
      });
      const data = await res.json();
      if (data.success) {
        setCurrentModelId(data.active_model.id);
        setModelName(data.active_model.name);
        // 重新获取模型列表
        const modelsRes = await fetch(`${apiUrl}/models`);
        const modelsData = await modelsRes.json();
        setModels(modelsData);
      } else {
        setError(data.error || '切换失败');
      }
    } catch (err) {
      setError('切换失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setError('请输入模型名称');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      if (isCreating) {
        const res = await fetch(`${apiUrl}/models`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData),
        });
        const data = await res.json();
        if (data.success) {
          const modelsRes = await fetch(`${apiUrl}/models`);
          const modelsData = await modelsRes.json();
          setModels(modelsData);
          setIsCreating(false);
          setEditingModel(null);
        } else {
          setError(data.error || '创建失败');
        }
      } else if (editingModel) {
        const res = await fetch(`${apiUrl}/models/${editingModel.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData),
        });
        const data = await res.json();
        if (data.success) {
          const modelsRes = await fetch(`${apiUrl}/models`);
          const modelsData = await modelsRes.json();
          setModels(modelsData);
          setEditingModel(null);
        } else {
          setError(data.error || '更新失败');
        }
      }
    } catch (err) {
      setError(isCreating ? '创建失败' : '更新失败');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--color-cream)] rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="bg-[var(--color-forest)] px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">模型配置</h2>
          <button
            onClick={onClose}
            className="text-white/70 hover:text-white text-2xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-6 overflow-y-auto max-h-[calc(80vh-60px)]">
          {/* 模型列表 */}
          {!isCreating && !editingModel && (
            <div className="space-y-3">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-sm font-medium text-gray-500">已配置模型</h3>
                <button
                  onClick={handleCreateNew}
                  className="px-3 py-1.5 bg-[var(--color-moss)] text-white text-sm rounded-lg hover:bg-[var(--color-moss-dark)] transition-colors"
                >
                  + 添加模型
                </button>
              </div>

              {models.map((model) => (
                <div
                  key={model.id}
                  className="bg-white rounded-xl p-4 shadow-sm border border-gray-100"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h4 className="font-medium text-[var(--color-wood)]">{model.name}</h4>
                        {model.is_active && (
                          <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">
                            使用中
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 mt-1">{model.api_base}</p>
                      <p className="text-xs text-gray-400">
                        Temperature: {model.temperature} | API Key: {model.api_key ? '已配置' : '未配置'}
                      </p>
                    </div>
                    <div className="flex gap-2 ml-4">
                      {!model.is_active && (
                        <button
                          onClick={() => handleSwitchModel(model.id)}
                          disabled={loading || !model.api_key}
                          className="px-3 py-1.5 bg-[var(--color-forest)] text-white text-sm rounded-lg hover:bg-[var(--color-forest-dark)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          切换
                        </button>
                      )}
                      <button
                        onClick={() => handleEdit(model)}
                        className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200 transition-colors"
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => handleDelete(model.id)}
                        disabled={models.length <= 1}
                        className="px-3 py-1.5 bg-red-50 text-red-600 text-sm rounded-lg hover:bg-red-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              ))}

              {models.length === 0 && (
                <div className="text-center py-8 text-gray-400">
                  暂无配置的模型
                </div>
              )}
            </div>
          )}

          {/* 创建/编辑表单 */}
          {(isCreating || editingModel) && (
            <div className="space-y-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-gray-500">
                  {isCreating ? '添加新模型' : '编辑模型'}
                </h3>
                <button
                  onClick={() => {
                    setIsCreating(false);
                    setEditingModel(null);
                  }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  返回列表
                </button>
              </div>

              {error && (
                <div className="p-3 bg-red-50 text-red-600 text-sm rounded-lg">
                  {error}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  模型名称
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="例如: MiniMax-M2.7"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--color-moss)]"
                />
              </div>

              {isCreating && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    模型 ID
                  </label>
                  <input
                    type="text"
                    value={formData.id}
                    onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                    placeholder="唯一标识符"
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--color-moss)]"
                  />
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  API Base
                </label>
                <input
                  type="text"
                  value={formData.api_base}
                  onChange={(e) => setFormData({ ...formData, api_base: e.target.value })}
                  placeholder="https://api.minimaxi.com/v1"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--color-moss)]"
                />
                <p className="text-xs text-gray-400 mt-1">
                  常见选项: MiniMax /api/minimaxi.com/v1, DeepSeek /api.deepseek.com/v1
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  API Key
                </label>
                <input
                  type="password"
                  value={formData.api_key}
                  onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                  placeholder="输入 API Key"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--color-moss)]"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Temperature: {formData.temperature}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={formData.temperature}
                  onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                  className="w-full accent-[var(--color-moss)]"
                />
                <div className="flex justify-between text-xs text-gray-400">
                  <span>精确</span>
                  <span>创意</span>
                </div>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  onClick={handleSubmit}
                  disabled={loading}
                  className="flex-1 px-4 py-2 bg-[var(--color-moss)] text-white rounded-lg hover:bg-[var(--color-moss-dark)] transition-colors disabled:opacity-50"
                >
                  {loading ? '保存中...' : '保存'}
                </button>
                <button
                  onClick={() => {
                    setIsCreating(false);
                    setEditingModel(null);
                  }}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ModelConfigModal;
