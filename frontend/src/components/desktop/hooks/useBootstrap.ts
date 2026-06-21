import { useEffect, useState } from 'react';
import { apiFetch } from '../../../lib/api';
import { useStore } from '../../../store/useStore';

export type BootstrapView = 'setup' | 'chat';

export interface BootstrapResult {
  /** 初始检查是否完成;未完成时 UI 应展示 loading。 */
  isBootstrapping: boolean;
  /** 根据 /api/models 是否有已配置模型决定:有 → 'chat',无 → 'setup'。 */
  initialView: BootstrapView;
  /** 活跃模型名（来自 models.json 的 is_active 或首条），未拿到时为 null。 */
  activeModelName: string | null;
}

interface ModelRow {
  api_key?: string;
  is_active?: boolean;
  name?: string;
}

/**
 * 桌面端首启 bootstrap:检查后端是否已有可用模型配置。
 * 用于在 'setup' 与 'chat' 视图之间做首启路由,同时把活跃模型名
 * 一次性写进 zustand store(之前 useModelNameLoader 单独再发一次
 * /api/model,合并后首屏少一次 RTT)。
 *
 * 网络/解析失败时保守地走 'setup',不阻塞用户。
 */
export function useBootstrap(): BootstrapResult {
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [initialView, setInitialView] = useState<BootstrapView>('setup');
  const [activeModelName, setActiveModelName] = useState<string | null>(null);
  const setModelName = useStore((state) => state.setModelName);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async (): Promise<void> => {
      try {
        const response = await apiFetch('/api/models');
        const models = (await response.json()) as ModelRow[];
        const hasConfiguredModel = models.some((model) => Boolean(model.api_key?.trim()));
        const active =
          models.find((model) => model.is_active) ?? models.find((model) => model.name);
        const name = active?.name?.trim() || null;

        if (cancelled) return;
        setInitialView(hasConfiguredModel ? 'chat' : 'setup');
        setActiveModelName(name);
        if (name) {
          setModelName(name);
        }
      } catch {
        if (!cancelled) {
          setInitialView('setup');
        }
      } finally {
        if (!cancelled) {
          setIsBootstrapping(false);
        }
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, [setModelName]);

  return { isBootstrapping, initialView, activeModelName };
}
