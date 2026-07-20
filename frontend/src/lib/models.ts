/**
 * 模型配置 API 封装 + store 刷新工具(2026-07-18)。
 *
 * 后端已支持完整多模型能力(nexus/backend/routes/model_config.py):
 *   - GET    /api/models          列表(api_key 掩码 "***xxxx")
 *   - POST   /api/models          新增(需唯一 id)
 *   - PUT    /api/models/{id}     更新(全字段可选,不传保留)
 *   - DELETE /api/models/{id}     删除(至少保留 1 个;删激活会自动 fallback)
 *   - POST   /api/models/switch   切换激活(重建后端 Agent)
 *
 * 本模块把这些端点封成 typed helper,并提供 `refreshModelsIntoStore`
 * 让 useBootstrap / 设置页 / 顶部切换器共用同一套"拉列表 → 灌 store"逻辑,
 * 修复此前 ModelSwitcher 下拉永远空(store.models 从未被填充)的根因。
 */
import type { Model } from '../types';
import { apiFetch } from './api';
import { useStore } from '../store';
import { DEFAULT_MODEL } from './config';

export type ModelRow = Model;

export interface CreateModelBody {
  id: string;
  name: string;
  api_key: string;
  api_base: string;
  temperature: number;
}

export type UpdateModelBody = Partial<Omit<CreateModelBody, 'id'>>;

/** 拉取模型列表(失败返回空数组,不抛)。 */
export async function fetchModels(): Promise<ModelRow[]> {
  try {
    const res = await apiFetch('/api/models');
    if (!res.ok) return [];
    const data = (await res.json()) as ModelRow[];
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

/**
 * 拉列表并灌入 store(models + 激活模型的 name/id)。
 * useBootstrap、设置页增删改、切换器切换后都调它保持单一真相源同步。
 */
export async function refreshModelsIntoStore(): Promise<ModelRow[]> {
  const models = await fetchModels();
  const active = models.find((m) => m.is_active) ?? models[0];
  const { setModels, setModelName, setCurrentModelId } = useStore.getState();
  setModels(models);
  if (active) {
    setModelName(active.name || DEFAULT_MODEL);
    setCurrentModelId(active.id ?? null);
  }
  return models;
}

/** 新增模型。成功返回 true。 */
export async function createModel(body: CreateModelBody): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch('/api/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return { ok: false, error: await readError(res) };
    return { ok: true };
  } catch {
    return { ok: false, error: '网络错误,请检查后端' };
  }
}

/** 更新模型(仅传要改的字段;api_key 留空表示不改)。 */
export async function updateModel(id: string, body: UpdateModelBody): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(`/api/models/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return { ok: false, error: await readError(res) };
    return { ok: true };
  } catch {
    return { ok: false, error: '网络错误,请检查后端' };
  }
}

/** 删除模型。 */
export async function deleteModel(id: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(`/api/models/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) return { ok: false, error: await readError(res) };
    return { ok: true };
  } catch {
    return { ok: false, error: '网络错误,请检查后端' };
  }
}

/** 切换激活模型(后端会重建 Agent,是重操作)。 */
export async function switchModel(id: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch('/api/models/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    if (!res.ok) return { ok: false, error: await readError(res) };
    return { ok: true };
  } catch {
    return { ok: false, error: '网络错误,请检查后端' };
  }
}

async function readError(res: Response): Promise<string> {
  const text = (await res.text().catch(() => '')).trim();
  if (!text) return `请求失败(${res.status})`;
  // FastAPI 错误体通常是 {"detail":"..."}
  try {
    const j = JSON.parse(text) as { detail?: string };
    if (j.detail) return j.detail;
  } catch {
    /* 非 JSON,用原文首行 */
  }
  return (text.split('\n')[0] ?? '').slice(0, 140);
}

// ============================================================================
// Provider 模型发现:给定 baseURL + apiKey,从 /models 拉取可用模型
// ============================================================================

export interface DiscoveredModel {
  id: string;
  name: string;
  owned_by: string;
}

export interface DiscoverResult {
  ok: boolean;
  models: DiscoveredModel[];
  count: number;
  error?: string;
}

export interface ImportResult {
  ok: boolean;
  imported: string[];
  count: number;
  error?: string;
}

/** 从 Provider 发现可用模型(只查询,不写入)。 */
export async function discoverProviderModels(baseUrl: string, apiKey: string): Promise<DiscoverResult> {
  try {
    const res = await apiFetch('/api/models/discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
    });
    if (!res.ok) return { ok: false, models: [], count: 0, error: await readError(res) };
    const data = (await res.json()) as { success: boolean; models: DiscoveredModel[]; count: number };
    return { ok: true, models: data.models ?? [], count: data.count ?? 0 };
  } catch {
    return { ok: false, models: [], count: 0, error: '网络错误,请检查后端' };
  }
}

/** 从 Provider 发现并导入全部模型到本地配置。 */
export async function importProviderModels(baseUrl: string, apiKey: string): Promise<ImportResult> {
  try {
    const res = await apiFetch('/api/models/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
    });
    if (!res.ok) return { ok: false, imported: [], count: 0, error: await readError(res) };
    const data = (await res.json()) as { success: boolean; imported: string[]; count: number };
    return { ok: true, imported: data.imported ?? [], count: data.count ?? 0 };
  } catch {
    return { ok: false, imported: [], count: 0, error: '网络错误,请检查后端' };
  }
}
