import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';

const e2eNexusHome = process.env.NEXUS_HOME ?? `${tmpdir()}/nexus-playwright-${process.pid}`;

/**
 * Nexus 前端 E2E 测试配置。
 *
 * 启动顺序：
 *   1. Playwright 先起后端 (uvicorn nexus.backend.main:app) on :30000
 *   2. 再起 Vite dev server on :30077
 *   3. Playwright 跑测试，baseURL=http://localhost:30077
 *
 * 关键约束：
 *   - minimax_api_key 必须注入到后端进程的环境变量，否则真实 LLM 不可用
 *   - Vite dev server 通过 VITE_API_TARGET=http://localhost:30000 把 /api 代理到后端
 *   - 串行执行（workers=1）：避免多个 spec 同时往同一个后端写污染数据库
 *   - 失败时保留 trace + video + screenshot，方便 CI 排错
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://localhost:30077',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // 后端 uvicorn（真实 LLM）
      // venv 路径优先级：NEXUS_HOME/.venv > VIRTUAL_ENV > 项目根 .venv
      // 启动方式：
      //   - 装了 nexus install 的环境：cd $NEXUS_HOME && python -m uvicorn nexus.backend.main:app
      //   - 项目源码环境：pip install -e ".[dev]" 后用项目根 .venv 直接 uvicorn
      command: (() => {
        const nexusHome = e2eNexusHome;
        const nexusVenv = `${nexusHome}/.venv/bin/python`;
        if (existsSync(nexusVenv)) {
          // 装了 nexus CLI 的环境：切到 NEXUS_HOME 跑（NEXUS_HOME 路径下有 nexus 包）
          return `cd ${nexusHome} && ${nexusVenv} -m uvicorn nexus.backend.main:app --host 127.0.0.1 --port 30000`;
        }
        return 'cd .. && ./.venv/bin/python -m uvicorn nexus.backend.main:app --host 127.0.0.1 --port 30000';
      })(),
      url: 'http://127.0.0.1:30000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        MINIMAX_API_KEY: process.env.MINIMAX_API_KEY ?? '',
        ANTHROPIC_AUTH_TOKEN: process.env.ANTHROPIC_AUTH_TOKEN ?? '',
        ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL ?? '',
        MODEL_NAME: process.env.MODEL_NAME ?? 'MiniMax-M3',
        NEXUS_HOME: e2eNexusHome,
        // 透传 mock LLM 开关。NEXUS_E2E_MOCK=1 时 nexus.backend.agent 加载
        // e2e_mock.py 替代真实 LLM(场景由 NEXUS_E2E_SCENARIO 决定),
        // 决定性触发 write_file 工具,无 LLM 行为不稳定问题,CI 100% 稳跑。
        // hitl-confirm.spec.ts 等期待 HITL 的 spec 在 mock 下会 skip 自己
        // (mock 默认 allow_nexus_write 不触发 HITL)。
        NEXUS_E2E_MOCK: process.env.NEXUS_E2E_MOCK ?? '0',
        NEXUS_E2E_SCENARIO: process.env.NEXUS_E2E_SCENARIO ?? 'allow_nexus_write',
      },
    },
    {
      // Vite dev server（前端）
      command: 'npm run dev -- --port 30077 --host 127.0.0.1',
      url: 'http://127.0.0.1:30077/app/',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        VITE_API_TARGET: 'http://127.0.0.1:30000',
      },
    },
  ],
});
