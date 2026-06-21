import { ChildProcessByStdio, spawn } from "node:child_process";
import type { Readable } from "node:stream";

type BackendChild = ChildProcessByStdio<null, Readable, Readable>;
import net from "node:net";
import path from "node:path";
import type { BackendLaunchConfig, BackendRuntime } from "./types.js";

// 用 process.versions.electron 检测而非 import { app },这样纯 Node 测试也能跑。
const IS_ELECTRON = typeof process.versions.electron === "string";

// 启动上限:包含 PyInstaller onefile 解压(_MEIPASS) + Python 解析器启动
// + uvicorn 导入 + /health 响应。在 SSD + M 系列 Mac 上 ~3-5s,在 HDD
// 或 FileVault 加密 APFS 冷启可达 15-20s。15s 在后者场景下首启会被误判。
// 延长到 45s 兼容冷启,同时给用户合理的等待预期(waitForHealth 自带
// 250ms 间隔轮询,不会真的等满 45s 才报错)。
const HEALTH_TIMEOUT_MS = 45_000;
const HEALTH_INTERVAL_MS = 250;    // 轮询间隔：250ms 比 500ms 早 1-2 tick 检测到 healthy
const SHUTDOWN_TIMEOUT_MS = 2_000;
const PORT_SCAN_LIMIT = 50;

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export async function waitForHealth(url: string, timeoutMs = HEALTH_TIMEOUT_MS): Promise<void> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(`${url}/health`);
      if (response.ok) {
        return;
      }
    } catch (error) {
      // The backend is still starting; timeout below turns repeated failures into a user-facing error.
    }

    await sleep(HEALTH_INTERVAL_MS);
  }

  throw new Error(`Nexus backend did not become healthy within ${timeoutMs}ms`);
}

async function isPortAvailable(host: string, port: number): Promise<boolean> {
  return await new Promise((resolve) => {
    const server = net.createServer();

    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

export async function findAvailablePort(host: string, preferredPort: number): Promise<number> {
  for (let offset = 0; offset < PORT_SCAN_LIMIT; offset += 1) {
    const candidatePort = preferredPort + offset;
    if (await isPortAvailable(host, candidatePort)) {
      return candidatePort;
    }
  }

  throw new Error(`No available backend port found from ${preferredPort} to ${preferredPort + PORT_SCAN_LIMIT - 1}`);
}

// 探测 preferred 端口是否已有 backend 在跑(由 CLI / launchd 管理)。
// 返回其 URL 或 null。
// 关键:避免 desktop 与 CLI 同时启动造成双 backend 占同一端口、
// 互相干扰 session / 配置 / 锁的问题。
export async function findExistingBackend(host: string, preferredPort: number): Promise<string | null> {
  const url = `http://${host}:${preferredPort}`;
  try {
    const response = await fetch(`${url}/health`, { signal: AbortSignal.timeout(500) });
    if (response.ok) {
      return url;
    }
  } catch {
    // 端口没监听 / /health 超时 → 没有 backend
  }
  return null;
}

// CORS：把 desktop 实际绑定的端口追加进允许来源列表。
// 后端 main.py 的 _cors_origins 默认只含 30077 / 8000 / tauri://localhost,
// desktop 通过 findAvailablePort 拿到的端口(30000~30049)不在内,
// 不注入则 CORSMiddleware 会拒绝所有 /api/* 和 /api/ws 升级请求。
export function buildDesktopCorsOrigins(port: number): string {
  return [
    "http://localhost:30077",
    "http://127.0.0.1:30077",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "tauri://localhost",
    `http://127.0.0.1:${port}`,
    `http://localhost:${port}`,
  ].join(",");
}

export async function startBackend(config: BackendLaunchConfig): Promise<BackendRuntime> {
  const corsOrigins = buildDesktopCorsOrigins(config.port);

  const backendProcess = spawn(config.command, config.args, {
    cwd: config.workingDirectory,
    env: {
      ...process.env,
      NEXUS_HOME: config.nexusHome,
      NEXUS_FRONTEND_DIST: config.frontendDist,
      NEXUS_HOST: config.host,
      NEXUS_PORT: String(config.port),
      NEXUS_ALLOWED_ORIGINS: corsOrigins,
    },
    // 关键:把 backend 放进独立的进程组。
    // - PyInstaller bootloader 会 fork 出一个子进程(实际跑 Python 解析器的 gateway),
    //   这个子进程继承我们的进程组 ID
    // - stopBackend 用 process.kill(-pid, 'SIGTERM') 一次清理整组,避免
    //   "主进程退出但 gateway worker 还在跑"的孤儿泄漏
    detached: true,
    stdio: ["ignore", "pipe", "pipe"]
  });

  // 关键:必须消费 stdout/stderr 的 Readable 流,否则内核 pipe buffer(~16-64KB)写满后
  // 子进程的 next write() 会阻塞,FastAPI event loop 停摆,UI 卡死。
  // - dev / 测试(纯 Node): 转发到 process.stdout/stderr,dev 体验对齐 CLI
  // - prod (Electron 打包): 静默丢弃(写日志文件后续再做,本 PR 优先解 deadlock)
  if (!IS_ELECTRON) {
    backendProcess.stdout.on("data", (chunk) => process.stdout.write(chunk));
    backendProcess.stderr.on("data", (chunk) => process.stderr.write(chunk));
  } else {
    backendProcess.stdout.resume();
    backendProcess.stderr.resume();
  }

  // detached 后,父进程退出不会自动 kill 子进程。我们用进程组显式管理。
  // 不调用 .unref() —— Electron 主进程 event loop 需要等 child handle,
  // 否则主进程可能不等 stopBackend 完成就退出。

  const url = `http://${config.host}:${config.port}`;
  await waitForHealth(url);

  return {
    url,
    pid: backendProcess.pid ?? null,
    stop: () => stopBackend(backendProcess)
  };
}

export async function stopBackend(backendProcess: BackendChild): Promise<void> {
  if (backendProcess.killed) {
    return;
  }

  await new Promise<void>((resolve) => {
    let resolved = false;

    const finish = (): void => {
      if (!resolved) {
        resolved = true;
        resolve();
      }
    };

    backendProcess.once("exit", finish);
    // 关键:用负 pid 把信号发到整个进程组,而不是只杀 backend 主进程。
    // PyInstaller bootloader 会 fork 出实际跑 Python 的 gateway worker,
    // 它继承我们的进程组 ID;只 SIGTERM 主进程会让 worker 变孤儿被 launchd 接管。
    const pid = backendProcess.pid;
    if (pid !== undefined && pid !== null) {
      try {
        process.kill(-pid, "SIGTERM");
      } catch {
        // 组不存在(已经退出了),fallback 到单进程 kill
        backendProcess.kill("SIGTERM");
      }
    } else {
      backendProcess.kill("SIGTERM");
    }

    setTimeout(() => {
      if (!backendProcess.killed) {
        if (pid !== undefined && pid !== null) {
          try {
            process.kill(-pid, "SIGKILL");
          } catch {
            backendProcess.kill("SIGKILL");
          }
        } else {
          backendProcess.kill("SIGKILL");
        }
      }
      finish();
    }, SHUTDOWN_TIMEOUT_MS);
  });
}
