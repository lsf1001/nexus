import { useEffect, useState } from 'react';
import { FALLBACK_VERSION, loadAppVersion } from '../lib/version';

/**
 * 返回应用版本号(用于关于页 / 侧栏页脚展示)。
 *
 * 挂载时异步加载 Tauri 真实版本,加载完成前显示 FALLBACK_VERSION,
 * 非 Tauri 环境(Web 预览)会直接停留在 FALLBACK_VERSION。
 */
export function useAppVersion(): string {
  const [version, setVersion] = useState(FALLBACK_VERSION);

  useEffect(() => {
    let alive = true;
    loadAppVersion()
      .then((v) => {
        if (alive) setVersion(v);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return version;
}
