/**
 * E2E 测试启动前的全局 setup:在 NEXUS_HOME 目录里 seed 一个有 api_key
 * 的 models.json。
 *
 * 背景(2026-06-28 事故):
 *   - backend load_models() 在 models.json 不存在时创建 default
 *     (api_key=""),useBootstrap 看到空 api_key 判定
 *     hasConfiguredModel=false → 走 'setup' 视图
 *   - 所有 E2E 在 /app/ 看不到 ChatView 的 .prompt-card,30s 超时 fail
 *     (27 个测试 × 3 retry 全 fail)
 *   - root cause:CI runner 没装过 nexus,`~/.nexus/models.json` 是
 *     后端运行时新建的空 api_key 文件
 *
 * 修法:在 backend 起来前,把 NEXUS_HOME/models.json 写好(api_key 占位,
 * E2E 走 mock LLM 不真发请求),useBootstrap 直接进 ChatView。
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const e2eNexusHome = process.env.NEXUS_HOME ?? `${tmpdir()}/nexus-playwright-${process.pid}`;

export default async function globalSetup(): Promise<void> {
  mkdirSync(e2eNexusHome, { recursive: true });
  const isMock = process.env.NEXUS_E2E_MOCK === '1';
  const seedModels = {
    models: [
      {
        id: 'e2e-default',
        name: process.env.MODEL_NAME ?? 'MiniMax-M3',
        // mock 模式填占位;真 LLM 模式用 secrets 注入的 key
        api_key: isMock
          ? 'e2e-mock-placeholder'
          : (process.env.MINIMAX_API_KEY ?? 'e2e-placeholder'),
        api_base: process.env.ANTHROPIC_BASE_URL ?? 'https://api.minimaxi.com/v1',
        temperature: 0.7,
        is_active: true,
      },
    ],
  };
  writeFileSync(
    join(e2eNexusHome, 'models.json'),
    JSON.stringify(seedModels, null, 2),
  );
  // eslint-disable-next-line no-console
  console.log(`[e2e-setup] seeded ${join(e2eNexusHome, 'models.json')}`);
}
