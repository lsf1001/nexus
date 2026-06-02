import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { Model } from '../types';

interface ModelConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onModelChange?: (name: string) => void;
}

function ModelConfigModal({ isOpen, onClose, onModelChange }: ModelConfigModalProps) {
  const models = useStore((s) => s.models);
  const setModels = useStore((s) => s.setModels);
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
      loadModels();
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen]);

  const loadModels = async () => {
    try {
      const res = await fetch(`${apiUrl}/models`);
      const data = await res.json();
      setModels(data);
    } catch {
      console.error('加载模型失败');
    }
  };

  const resetForm = () => {
    setFormData({
      id: `model-${Date.now()}`,
      name: '',
      api_key: '',
      api_base: 'https://api.minimaxi.com/v1',
      temperature: 0.7,
    });
    setEditingModel(null);
    setIsCreating(false);
    setError(null);
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleCreateNew = () => {
    setIsCreating(true);
    setEditingModel(null);
    setFormData({
      id: `model-${Date.now()}`,
      name: '',
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
    try {
      const res = await fetch(`${apiUrl}/models/${modelId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        await loadModels();
      } else {
        setError(data.error || '删除失败');
      }
    } catch {
      setError('删除失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSwitch = async (modelId: string) => {
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/models/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: modelId }),
      });
      const data = await res.json();
      if (data.success) {
        await loadModels();
        onModelChange?.(data.active_model.name);
      } else {
        setError(data.error || '切换失败');
      }
    } catch {
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
          await loadModels();
          resetForm();
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
          await loadModels();
          resetForm();
        } else {
          setError(data.error || '更新失败');
        }
      }
    } catch {
      setError(isCreating ? '创建失败' : '更新失败');
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={handleClose}>
      <div className="bg-white rounded-3xl w-full max-w-md shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 bg-[#2d4a3a]">
          <h2 className="text-lg font-semibold text-white">模型配置</h2>
          <button
            onClick={handleClose}
            className="w-8 h-8 rounded-full bg-[#4a7c59] hover:bg-[#8fbc8f] text-white flex items-center justify-center transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {/* 模型列表 */}
          {!isCreating && !editingModel && (
            <div className="space-y-3">
              {models.map((model) => (
                <div
                  key={model.id}
                  className={`p-4 rounded-2xl border transition-all ${
                    model.is_active
                      ? 'border-[#4a7c59] bg-[#f0f7f1]'
                      : 'border-[#e0dcd4] hover:border-[#8fbc8f]'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-[#2d4a3a]">{model.name}</span>
                        {model.is_active && (
                          <span className="px-2 py-0.5 bg-[#4a7c59] text-white text-xs rounded-full">
                            使用中
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[#6b7c6b] mt-1">{model.api_base}</p>
                      <p className="text-xs text-[#6b7c6b]">
                        Temperature: {model.temperature}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {!model.is_active && (
                        <button
                          onClick={() => handleSwitch(model.id)}
                          disabled={loading || !model.api_key}
                          className="px-3 py-1 text-xs rounded-lg bg-[#4a7c59] text-white hover:bg-[#2d4a3a] disabled:opacity-50"
                        >
                          切换
                        </button>
                      )}
                      <button
                        onClick={() => handleEdit(model)}
                        className="px-3 py-1 text-xs rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600"
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => handleDelete(model.id)}
                        disabled={models.length <= 1}
                        className="px-3 py-1 text-xs rounded-lg text-red-500 hover:bg-red-50 disabled:opacity-50"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              ))}

              {/* 添加按钮 */}
              <button
                onClick={handleCreateNew}
                className="w-full py-3 rounded-xl border-2 border-dashed border-[#e0dcd4] text-[#6b7c6b] hover:border-[#4a7c59] hover:text-[#4a7c59] transition-colors"
              >
                + 添加模型
              </button>
            </div>
          )}

          {/* 表单 */}
          {(isCreating || editingModel) && (
            <div className="space-y-4">
              {error && (
                <div className="p-3 bg-red-50 text-red-600 text-sm rounded-xl">{error}</div>
              )}

              <div>
                <label className="block text-sm font-medium text-[#2d4a3a] mb-1">模型名称</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="例如: MiniMax-M2.7"
                  className="w-full px-3 py-2 rounded-xl border border-[#e0dcd4] focus:border-[#4a7c59] focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-[#2d4a3a] mb-1">API Base</label>
                <input
                  type="text"
                  value={formData.api_base}
                  onChange={(e) => setFormData({ ...formData, api_base: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-[#e0dcd4] focus:border-[#4a7c59] focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-[#2d4a3a] mb-1">API Key</label>
                <input
                  type="password"
                  value={formData.api_key}
                  onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                  placeholder="输入 API Key"
                  className="w-full px-3 py-2 rounded-xl border border-[#e0dcd4] focus:border-[#4a7c59] focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-[#2d4a3a] mb-1">
                  Temperature: {formData.temperature}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.1"
                  value={formData.temperature}
                  onChange={(e) => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
                  className="w-full accent-[#4a7c59]"
                />
                <div className="flex justify-between text-xs text-[#6b7c6b]">
                  <span>精确</span>
                  <span>创意</span>
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleSubmit}
                  disabled={loading}
                  className="flex-1 py-2 rounded-xl bg-[#4a7c59] text-white hover:bg-[#2d4a3a] disabled:opacity-50 transition-colors"
                >
                  {loading ? '保存中...' : '保存'}
                </button>
                <button
                  onClick={resetForm}
                  className="px-4 py-2 rounded-xl bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
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
