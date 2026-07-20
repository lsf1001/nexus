import { getVersion } from '@tauri-apps/api/app';

/**
 * 前端展示用的应用版本号。
 *
 * 桌面端(Tauri)运行时通过 getVersion() 读取 tauri.conf.json 的真实版本;
 * 非 Tauri 环境(Web 预览 / 单元测试)无法调用,回退到 FALLBACK_VERSION。
 *
 * 单一来源,集中管理,避免 PreferencesModal / Sidebar 各自硬编码字符串,
 * 导致与 tauri.conf.json 的 version 字段不一致(此前曾出现前端写 1.3.0、
 * tauri.conf 实为 1.1.0 的偏差)。
 */
export const FALLBACK_VERSION = '1.1.0';

let cached: string | null = null;

/** 读取应用版本,结果带内存缓存;失败回退 FALLBACK_VERSION。 */
export async function loadAppVersion(): Promise<string> {
  if (cached) return cached;
  try {
    cached = await getVersion();
  } catch {
    cached = FALLBACK_VERSION;
  }
  return cached;
}
