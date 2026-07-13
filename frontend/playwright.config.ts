import { defineConfig, devices } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { homedir } from 'node:os';

// 路径必须与 webServer.env.NEXUS_HOME 完全一致:
// seedCmd 写到 $NEXUS_HOME/.nexus/models.json,但后端 load_models() 读
// NEXUS_HOME/.nexus/models.json。两边都得是同一个值,否则 CI 写一份、
// 后端读 ~/.nexus/models.json(api_key=空)→ useBootstrap 进 'setup' 视图。
const e2eNexusHome = `${tmpdir()}/nexus-playwright-${process.pid}`;

/**
 * 从 ~/.nexus/models.json 拿 active 模型的 api_key / api_base / name。
 *
 * WHY:用户反馈"你不是用过吗 每次都问我要什么"——shell 经常没 export
 * MINIMAX_API_KEY,但 ~/.nexus/models.json 里已经有现成的真实 key(用户在
 * UI 上配的)。这条路径优先读这个,避免 dev 每次手动 export。
 *
 * 返回 null 时,seed 用 e2e-placeholder(常见情况:CI runner 没有
 * ~/.nexus/models.json,只能依赖 shell env)。
 */
function loadActiveModelFromHome(): {
  api_key: string;
  api_base: string;
  name: string;
} | null {
  const homeModels = join(homedir(), '.nexus', 'models.json');
  if (!existsSync(homeModels)) return null;
  try {
    const data = JSON.parse(readFileSync(homeModels, 'utf-8'));
    const models = Array.isArray(data?.models) ? data.models : [];
    const active = models.find((m: { is_active?: boolean }) => m.is_active) ?? models[0];
    if (!active) return null;
    return {
      api_key: String(active.api_key ?? ''),
      api_base: String(active.api_base ?? 'https://api.minimaxi.com/v1'),
      name: String(active.name ?? 'MiniMax-M3'),
    };
  } catch {
    return null;
  }
}

const homeModel = loadActiveModelFromHome();
// shell env(只读 MINIMAX_API_BASE) > hardcoded minimax public base
//
// WHY 不读 ~/.nexus/models.json 的 api_base:那个文件是用户在 Claude Desktop
// 上配的,base 指向 Claude Desktop 本地 proxy (http://127.0.0.1:15721/...)
// — 不能用于 E2E(2026-07-13 修)。
//
// WHY 不读 shell 的 ``ANTHROPIC_BASE_URL``:local dev shell 通常为 Claude
// Desktop proxy 设了这个 env;Playwright 直接透传会让 backend 拿 Claude
// Desktop proxy 当 LLM endpoint → POST /chat/completions 返回 404
// (proxy 不识别 ``MiniMax-M3`` 模型)。E2E 100% 必 fail。
// 唯一允许的覆盖是 ``MINIMAX_API_BASE``,用户显式设来指向其他兼容端点
// (如 apihub.agnes-ai.com)。其他 base 全部忽略。
const effectiveApiKey =
  process.env.MINIMAX_API_KEY || homeModel?.api_key || 'e2e-placeholder';
const effectiveApiBase =
  process.env.MINIMAX_API_BASE || 'https://api.minimaxi.com/v1';
const effectiveModelName =
  process.env.MODEL_NAME || homeModel?.name || 'MiniMax-M3';

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
        // 在 uvicorn 启动前 seed models.json(api_key 占位),否则 backend
        // load_models() 看到文件不存在 → 创建 default(api_key=空) →
        // useBootstrap 走 'setup' 视图 → ChatView .prompt-card 不渲染 →
        // 所有 E2E 在 30s 超时 fail (2026-06-28 事故 27 spec 全 fail)。
        // 必须 inline 到 uvicorn 启动前 — globalSetup 与 webServer 并行,
        // 实测会晚 1s 写文件(后端已加载 default),仍 fail。
        // 用 python -c 写文件(无 heredoc,无 shell 解析陷阱),spawn shell 拿
        // JSON.stringify(...) 直接当 args,避开 heredoc 在某些 shell 下被吞的
        // 问题(2026-07-01 实测 local + CI heredoc 不工作,/tmp/.../models.json
        // 根本不存在)。
        const isMock = process.env.NEXUS_E2E_MOCK === '1';
        const apiKey = isMock ? 'e2e-mock-placeholder' : effectiveApiKey;
        const seedPayload = JSON.stringify({
          models: [{
            id: 'e2e-default',
            name: effectiveModelName,
            api_key: apiKey,
            api_base: effectiveApiBase,
            temperature: 0.7,
            is_active: true,
          }],
        });
        // python -c 写文件 + 起 uvicorn 一气呵成,seed 一定在 uvicorn 启动前完成。
        // WHY 用绝对路径,不依赖 os.environ['NEXUS_HOME']:Playwright 的 webServer
        // env 不会自动注入到 command 内 python3 子进程(实测 2026-07-01 KeyError),
        // 直接把 nexusHome 拼进 python 脚本里(shell 转义 JSON.stringify 已经处理
        // 引号),保证 seed 100% 落到正确路径。
        const seedCmd = `mkdir -p ${nexusHome}/.nexus && python3 -c 'import json; open(${JSON.stringify(`${nexusHome}/.nexus/models.json`)},"w").write(${JSON.stringify(seedPayload)})'`;
        // 把 backend stdout/stderr 写到 /tmp/nexus-e2e-backend-${pid}.log
        // (Playwright 默认 pipe 不落盘,debug 看不到 LLM 请求日志)。
        const backendLog = `/tmp/nexus-e2e-backend-${process.pid}.log`;
        if (existsSync(nexusVenv)) {
          // 装了 nexus CLI 的环境：切到 NEXUS_HOME 跑（NEXUS_HOME 路径下有 nexus 包）
          return `${seedCmd} && cd ${nexusHome} && ${nexusVenv} -m uvicorn nexus.backend.main:app --host 127.0.0.1 --port 30000 > ${backendLog} 2>&1`;
        }
        return `${seedCmd} && cd .. && ./.venv/bin/python -m uvicorn nexus.backend.main:app --host 127.0.0.1 --port 30000 > ${backendLog} 2>&1`;
      })(),
      url: 'http://127.0.0.1:30000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
      // 把 backend stdout/stderr 写到 /tmp 让 debug 时能看
      // (Playwright 默认只 pipe,test pass 时静默丢,fail 也只显示摘要)
      // E2E 2026-07-13 debug:NotFoundError 404 反复出现,但 stderr 没 leak,
      // 加 stdout/stderr 文件路径让 debug 时能直接 tail。
      // WHY 不在每次重跑时 unlink:append 模式 + 后端启动时间戳命名,
      // 多个 spec 各自独立 log 文件,不会互相覆盖。
      env: {
        MINIMAX_API_KEY: effectiveApiKey,
        ANTHROPIC_AUTH_TOKEN: process.env.ANTHROPIC_AUTH_TOKEN ?? '',
        ANTHROPIC_BASE_URL: effectiveApiBase,
        MODEL_NAME: effectiveModelName,
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
        // 2026-07-12 修复:Vite 编译期 env 必须与后端 NEXUS_WS_TOKEN 一致,
        // 否则 apiFetch 的 Authorization: Bearer header 缺失 → 后端 401 → 前端
        // useBootstrap 收到 401 → SetupView 兜底 → ChatView 不渲染 → 所有
        // E2E 在 30s 后 fail(openHome 等不到 prompt-card)。回退到与后端同款
        // 默认 token,与 CLAUDE.md / env 表对齐。
        VITE_NEXUS_WS_TOKEN: process.env.NEXUS_WS_TOKEN ?? 'nexus-default-token',
      },
    },
  ],
});
