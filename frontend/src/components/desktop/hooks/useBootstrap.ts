import { useEffect, useState } from 'react';
import { apiFetch } from '../../../lib/api';

export type BootstrapView = 'setup' | 'chat';

export interface BootstrapResult {
  /** 初始检查是否完成;未完成时 UI 应展示 loading。 */
  isBootstrapping: boolean;
  /** 根据 /api/models 是否有已配置模型决定:有 → 'chat',无 → 'setup'。 */
  initialView: BootstrapView;
}

interface ModelRow {
  api_key?: string;
  is_active?: boolean;
  name?: string;
}

/**
 * 桌面端首启 bootstrap:检查后端是否已有可用模型配置。
 * 用于在 'setup' 与 'chat' 视图之间做首启路由。
 *
 * 网络/解析失败时保守地走 'setup',不阻塞用户。
 *
 * 历史:Plan 4 §Phase 3 删除 activeModelName 返回值(无消费者 — DesktopShell
 * 解构 useBootstrap 只取 isBootstrapping / initialView)。setModelName 副作用
 * 仍保留在 useStore.conversations slice 中供 ModelConfigModal 切模型同步用。
 */
export function useBootstrap(): BootstrapResult {
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [initialView, setInitialView] = useState<BootstrapView>('setup');

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async (): Promise<void> => {
      try {
        const response = await apiFetch('/api/models');
        const models = (await response.json()) as ModelRow[];
        const hasConfiguredModel = models.some((model) => Boolean(model.api_key?.trim()));

        if (cancelled) return;
        setInitialView(hasConfiguredModel ? 'chat' : 'setup');
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
  }, []);

  return { isBootstrapping, initialView };
}
