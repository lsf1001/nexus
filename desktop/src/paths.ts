import { app } from "electron";
import path from "node:path";
import os from "node:os";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { BackendLaunchConfig } from "./types.js";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);
const DEFAULT_BACKEND_PORT = 30000;

function pathExists(p: string): boolean {
  try {
    return existsSync(p);
  } catch {
    return false;
  }
}

export function getProjectRoot(): string {
  if (!app.isPackaged) {
    return path.resolve(currentDir, "..", "..", "..");
  }
  return process.resourcesPath;
}

export function getNexusHome(): string {
  // 与 nexus/cli/gateway.py:_get_nexus_home / nexus/backend/config.py 对齐：
  // 默认 ~/.nexus，CLI 与 Desktop 共用同一份 DB / 配置 / 记忆，
  // 用户从 CLI 切到 DMG 不会丢失会话。
  // 尊重 NEXUS_HOME 环境变量覆盖（与 Python 后端行为一致）。
  const fromEnv = process.env.NEXUS_HOME?.trim();
  if (fromEnv) {
    return fromEnv;
  }
  return path.join(os.homedir(), ".nexus");
}

export function getDefaultBackendPort(): number {
  return DEFAULT_BACKEND_PORT;
}

export function getBackendLaunchConfig(port = DEFAULT_BACKEND_PORT): BackendLaunchConfig {
  const projectRoot = getProjectRoot();

  if (app.isPackaged) {
    // 优先 onedir 布局（dist/nexus-backend/nexus-backend），回退 onefile（单文件）
    const onedirExec = path.join(process.resourcesPath, "nexus-backend", "nexus-backend");
    const onefileExec = path.join(process.resourcesPath, "nexus-backend");
    const backendExecutable = pathExists(onedirExec) ? onedirExec : onefileExec;
    return {
      projectRoot,
      workingDirectory: process.resourcesPath,
      command: backendExecutable,
      args: ["--host", "127.0.0.1", "--port", String(port)],
      host: "127.0.0.1",
      port,
      nexusHome: getNexusHome(),
      frontendDist: path.join(process.resourcesPath, "frontend", "dist")
    };
  }

  return {
    projectRoot,
    workingDirectory: projectRoot,
    command: path.join(projectRoot, ".venv", "bin", "python"),
    args: ["nexus/backend/run.py", "--host", "127.0.0.1", "--port", String(port)],
    host: "127.0.0.1",
    port,
    nexusHome: getNexusHome(),
    frontendDist: path.join(projectRoot, "frontend", "dist")
  };
}

export function getFrontendUrl(port = DEFAULT_BACKEND_PORT): string {
  return `http://127.0.0.1:${port}/app`;
}
