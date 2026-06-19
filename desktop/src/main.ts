import { BrowserWindow, app, dialog } from "electron";

// QA 模式:NEXUS_DEVTOOLS=1 时打开 Chrome DevTools 远程调试端口(9229),
// 让 Puppeteer/CDP 能 attach 到 renderer 实现真实 GUI 自动化测试。
// 必须在 app 初始化前调用(commandLine switches 启动前注册)。
if (process.env.NEXUS_DEVTOOLS === "1") {
  app.commandLine.appendSwitch("remote-debugging-port", "9229");
  app.commandLine.appendSwitch("remote-allow-origins", "*");
}
import path from "node:path";
import { findAvailablePort, findExistingBackend, startBackend } from "./backend.js";
import { getBackendLaunchConfig, getDefaultBackendPort, getFrontendUrl } from "./paths.js";
import type { BackendRuntime } from "./types.js";

let mainWindow: BrowserWindow | null = null;
let backendRuntime: BackendRuntime | null = null;
let backendPid: number | null = null;  // 同步兜底:exit event 里用得到
let isQuitting = false;

async function createWindow(): Promise<void> {
  const host = "127.0.0.1";
  const preferredPort = getDefaultBackendPort();

  // 优先 attach 到已有的 backend(由 CLI / launchd 管理的实例),
  // 避免双 backend 端口冲突、数据不一致。
  // desktop 自己 spawn 的 backend 只在 CLI backend 不存在时启动,
  // 退出时也只 kill 自己 spawn 的,不会误杀 CLI 守护的实例。
  const existingUrl = await findExistingBackend(host, preferredPort);
  let port: number;
  if (existingUrl) {
    port = preferredPort;
  } else {
    port = await findAvailablePort(host, preferredPort);
  }

  const preloadPath = path.join(app.getAppPath(), "dist", "src", "preload.js");

  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 720,
    title: "Nexus",
    backgroundColor: "#f6f1e7",
    titleBarStyle: "hiddenInset",
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      // QA:开发/CI 时通过 NEXUS_DEVTOOLS=1 环境变量打开 DevTools 和
      // remote debugging 端口(9229)。Puppeteer/CDP 可连,实现真实 GUI 注入测试。
      // 生产构建不开 — 避免暴露 renderer 调试面。
      devTools: process.env.NEXUS_DEVTOOLS === "1",
    },
  });
  if (process.env.NEXUS_DEVTOOLS === "1") {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  try {
    if (existingUrl) {
      // attach 模式:不 spawn、不 stop(externally-managed backend)
      backendRuntime = {
        url: existingUrl,
        pid: null,
        stop: async () => {
          // 故意 noop:CLI / launchd 管理的 backend 不归 desktop 管
        }
      };
    } else {
      backendRuntime = await startBackend(getBackendLaunchConfig(port));
    }
    backendPid = backendRuntime.pid;  // 给 exit event 留个引用
    await mainWindow.loadURL(getFrontendUrl(port));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "Nexus 启动失败",
      message: "本地服务没有成功启动。",
      detail: message
    });
  }
}

app.whenReady().then(createWindow).catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Nexus desktop failed to start: ${message}`);
});

// macOS HIG：关窗后不要退出 app，留在 dock；Cmd-Q 才走 before-quit 真正退。
// 其它平台保持 quit-on-close 行为。
// 关键修复:macOS 关窗后 backend 进程如果不显式杀,会留在后台变孤儿,
// 反复开关窗会越积越多。这里统一在 window-all-closed 时停 backend,
// darwin 上虽然不退出 app,但 backend 停掉就释放端口和内存。
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
    return;
  }
  // darwin: 关窗后停 backend(下次 activate 会重建)
  if (backendRuntime) {
    const runtime = backendRuntime;
    backendRuntime = null;
    backendPid = null;
    void runtime.stop().catch(() => {});
  }
});

// dock 图标点击且无窗口时重建主窗口（macOS 必需，否则关窗后点 dock 无反应）。
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindow();
  }
});

app.on("before-quit", async (event) => {
  if (isQuitting || !backendRuntime) {
    return;
  }

  event.preventDefault();
  isQuitting = true;
  const runtime = backendRuntime;
  backendRuntime = null;
  backendPid = null;  // 即将同步 stop,exit event 不需要再 kill
  // 关键:必须用 try/finally 包住 await runtime.stop(),
  // 否则 stopBackend 抛错(ESRCH / detached 进程组已不存在)时
  // app.quit() 永不执行,Electron 卡在 quit 中间态,Cmd-Q 二次失效,
  // 只能从 Dock 强制退出。
  try {
    await runtime.stop();
  } catch (error) {
    console.error(`backend stop failed during quit: ${error}`);
  } finally {
    app.quit();
  }
});

// 兜底:任何外部信号(SIGINT/Ctrl-C、SIGHUP、崩溃后 launchd 回收)到达时,
// 同步强杀 backend 进程组。before-quit 不一定有机会跑。
function forceKillBackendSync(): void {
  if (!backendRuntime) return;
  const runtime = backendRuntime;
  backendRuntime = null;
  backendPid = null;
  // fire-and-forget;Electron 主进程 event loop 在 app.quit 后会等 promise
  void runtime.stop().catch(() => {});
}

process.on("SIGINT", () => {
  forceKillBackendSync();
  app.quit();
});

process.on("SIGTERM", () => {
  forceKillBackendSync();
  app.quit();
});

process.on("SIGHUP", () => {
  forceKillBackendSync();
  app.quit();
});

// 同步兜底:Node 进程退出(exit event)时,同步强杀整个 backend 进程组。
// 这个 hook 只能跑同步代码,所以用同步 process.kill(-pid, SIGKILL)。
// 关键:不只 kill 主进程(nexus-backend binary),而是进程组(负 pid),因为
// PyInstaller bootloader 会 fork 出实际跑 Python 的 gateway worker,worker
// 继承我们 spawn 时设的进程组 ID。只 kill 主进程会让 worker 变孤儿被
// launchd 接管,造成 nexus-gateway 永久泄漏。
// 覆盖:before-quit 没机会跑的崩溃路径(主进程 abort、Electron renderer
// 触发主进程 panic、macOS launchd 突然给父进程发 SIGKILL 等)。
process.on("exit", () => {
  if (backendPid !== null) {
    try {
      // 负 pid = 整组。Escalate 到 SIGKILL,不优雅但保证清理。
      process.kill(-backendPid, "SIGKILL");
    } catch {
      // 子进程已经死了,忽略 ESRCH
    }
  }
});
