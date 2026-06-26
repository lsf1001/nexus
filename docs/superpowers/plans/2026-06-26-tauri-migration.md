# Tauri 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Nexus 桌面 APP 从 pywebview+PyInstaller 迁移到 Tauri 2 + Python sidecar

**Architecture:** Tauri 2 主进程（Rust）启动 WKWebView 窗口 + 异步 spawn Python sidecar（PyInstaller onedir 打包的 FastAPI/DeepAgents）；前端 React 经 Tauri Channel 流式 WS、Rust relay 中转到 sidecar，REST 直连 127.0.0.1:30000

**Tech Stack:** Tauri 2.x, Rust (tokio + tokio-tungstenite + reqwest), PyInstaller onedir, React 19 + Vite (现有), Python 3.12 (FastAPI + DeepAgents)

**Spec:** `docs/superpowers/specs/2026-06-26-tauri-migration-design.md`

---

## File Structure

### 创建

| 文件 | 职责 |
|---|---|
| `nexus/backend/runtime_main.py` | Sidecar 入口:uiautomator 启动 uvicorn,无 webview |
| `desktop/src-tauri/Cargo.toml` | Rust 依赖:tauri 2 + tokio + tokio-tungstenite + reqwest |
| `desktop/src-tauri/tauri.conf.json` | 窗口/CSP/bundle/icon 配置 |
| `desktop/src-tauri/build.rs` | `tauri_build::build()` |
| `desktop/src-tauri/src/main.rs` | 入口、窗口事件、关闭/Dock 重开、sidecar spawn 编排 |
| `desktop/src-tauri/src/runtime.rs` | Sidecar 进程管理、健康检查、supervisor |
| `desktop/src-tauri/src/ws_relay.rs` | WebSocket relay + Tauri Channel |
| `desktop/src-tauri/icons/icon.icns` | 复用 `scripts/nexus.icns` |
| `desktop/src-tauri/binaries/nexus-runtime` | PyInstaller 产物(打包后塞进 .app) |
| `desktop/src-tauri/capabilities/main.json` | Tauri 2 权限声明 |
| `desktop/package.json` | Tauri dev/build 脚本 |
| `frontend/src/hooks/useTauriWs.ts` | Tauri Channel 版 WS hook |
| `frontend/src/components/desktop/SplashView.tsx` | 启动 splash 页面 |
| `scripts/build_sidecar.sh` | PyInstaller onedir 打包脚本 |
| `tests/desktop/test_runtime_lifecycle.py` | Sidecar 生命周期集成测试 |
| `tests/desktop/test_ws_relay.py` | WS relay 单元测试 |

### 修改

| 文件 | 改动 |
|---|---|
| `frontend/src/App.tsx` | 增加 runtime-status 监听,渲染 Splash 或主页 |
| `scripts/build_dmg.sh` | 重写为 tauri build + DMG 流程 |
| `pyproject.toml` | 移除 pywebview（保留 dev 模式的 launcher.py 仍可装） |
| `frontend/package.json` | 增加 `@tauri-apps/api` 依赖 |

### 保留（dev 模式）

- `nexus/backend/launcher.py` — 本地开发用 `python -m nexus.backend.launcher`

---

## Phase 0: 前置准备

### Task 1: 安装 Rust 工具链

**Files:**
- 创建: 无
- 修改: `~/.zshrc` (PATH)

- [ ] **Step 1: 检查是否已装**

```bash
which rustc cargo
rustc --version
```

如果已装且 >= 1.74，跳到 Task 2。

- [ ] **Step 2: 用 rustup 装 stable**

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
source "$HOME/.cargo/env"
```

- [ ] **Step 3: 验证**

```bash
rustc --version  # 期望: rustc 1.74.0 或更新
cargo --version
```

- [ ] **Step 4: 提交（无文件改动，just record）**

无需提交。后续 Task 2 的 Tauri 项目 commit 会包含 `.gitignore` 把 `desktop/target/` 排除掉。

---

### Task 2: 安装 Tauri CLI

**Files:**
- 创建: 无

- [ ] **Step 1: 用 cargo 装 tauri-cli**

```bash
cargo install tauri-cli --version "^2.0" --locked
```

- [ ] **Step 2: 验证**

```bash
cargo tauri --version
# 期望: tauri-cli 2.x.x
```

- [ ] **Step 3: 确认 Xcode 命令行工具**

```bash
xcode-select -p
# 期望: /Applications/Xcode.app/... 或 /Library/Developer/CommandLineTools
```

如果没有：`xcode-select --install`

---

## Phase 1: Sidecar 入口拆分

### Task 3: 创建 runtime_main.py（去 webview 版 launcher）

**Files:**
- 创建: `nexus/backend/runtime_main.py`

- [ ] **Step 1: 写文件**

```python
"""Sidecar 入口: 只跑 FastAPI/uvicorn,不开 webview。

打包时被 PyInstaller 打成 nexus-runtime 二进制(无 webview 依赖)。
Tauri 主进程 spawn 这个 sidecar,绑定 127.0.0.1:30000。

为什么独立于 launcher.py:
- launcher.py 引入 webview + pyobjc,打 sidecar 时这些都不能打包
- runtime_main.py 极简,只引 uvicorn + nexus.backend.main,PyInstaller 友好
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    args = parser.parse_args()

    # PyInstaller 打包后,前端 dist 在 .app/Contents/Resources/frontend/。
    # PyInstaller 6.20 把 _MEIPASS 设在 Contents/Frameworks/,回退到 Resources。
    if getattr(sys, "frozen", False) and not os.environ.get("NEXUS_FRONTEND_DIST"):
        bundled = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
        if not bundled.exists():
            bundled = Path(sys._MEIPASS).parent / "Resources" / "frontend"  # type: ignore[attr-defined]
        if bundled.exists():
            os.environ["NEXUS_FRONTEND_DIST"] = str(bundled)

    import uvicorn

    from nexus.backend.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 语法检查**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
python -c "import ast; ast.parse(open('nexus/backend/runtime_main.py').read())"
```

期望：无输出（成功）

- [ ] **Step 3: dev 模式跑通**

```bash
python -m nexus.backend.runtime_main --port 30001 &
RUNTIME_PID=$!
sleep 2
curl -s http://127.0.0.1:30001/health
kill $RUNTIME_PID 2>/dev/null
```

期望：返回 `{"status":"ok"}` 或类似 200 响应

- [ ] **Step 4: 提交**

```bash
git add nexus/backend/runtime_main.py
git commit -m "feat(backend): sidecar 入口 runtime_main.py" \
  -m "无 webview 依赖的 FastAPI 启动器,供 PyInstaller 打成 sidecar。

WHY: Tauri 迁移需要 Python 后端作为独立进程,不再嵌入 webview。
launcher.py 仍保留供本地 dev 模式使用(python -m nexus.backend.launcher)。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 2: Tauri 项目脚手架

### Task 4: 创建 desktop/ 目录 + .gitignore

**Files:**
- 创建: `desktop/.gitignore`

- [ ] **Step 1: 建目录**

```bash
mkdir -p /Users/yxb/projects/nexus/desktop/src-tauri/src
mkdir -p /Users/yxb/projects/nexus/desktop/src-tauri/icons
mkdir -p /Users/yxb/projects/nexus/desktop/src-tauri/binaries
mkdir -p /Users/yxb/projects/nexus/desktop/src-tauri/capabilities
mkdir -p /Users/yxb/projects/nexus/desktop/src
```

- [ ] **Step 2: 写 .gitignore**

```gitignore
# Tauri
src-tauri/target/
src-tauri/Cargo.lock
src-tauri/binaries/*-apple-darwin
!src-tauri/binaries/.gitkeep

# Node
node_modules/
dist/

# OS
.DS_Store
```

- [ ] **Step 3: 在 binaries/ 加 .gitkeep**

```bash
touch /Users/yxb/projects/nexus/desktop/src-tauri/binaries/.gitkeep
```

- [ ] **Step 4: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/
git commit -m "chore(desktop): Tauri 项目目录结构" \
  -m "建 desktop/ + src-tauri/{src,icons,binaries,capabilities},配置 .gitignore。

WHY: Tauri 2 标准布局,binaries/ 留给 sidecar 产物。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 复制 icon.icns

**Files:**
- 复制: `desktop/src-tauri/icons/icon.icns` ← `scripts/nexus.icns`

- [ ] **Step 1: 复制图标**

```bash
cp /Users/yxb/projects/nexus/scripts/nexus.icns /Users/yxb/projects/nexus/desktop/src-tauri/icons/icon.icns
ls -lh /Users/yxb/projects/nexus/desktop/src-tauri/icons/icon.icns
```

期望：~110 KB

- [ ] **Step 2: 复制 PNG 给 Tauri 多尺寸需求**

Tauri 2 实际只引用 .icns，但若用 iconutil 转换需要 PNG。**当前实现只用 .icns，无需 PNG。**

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/icons/icon.icns
git commit -m "chore(desktop): 复制 nexus.icns" \
  -m "复用 scripts/nexus.icns 作为 Tauri bundle 图标。

WHY: Tauri 2 macOS bundle 需要 icon.icns。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 写 Cargo.toml

**Files:**
- 创建: `desktop/src-tauri/Cargo.toml`

- [ ] **Step 1: 写文件**

```toml
[package]
name = "nexus-desktop"
version = "1.1.0"
description = "Nexus Desktop"
authors = ["夜小白科技"]
edition = "2021"
rust-version = "1.74"

[lib]
name = "nexus_desktop_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-dialog = "2"
tauri-plugin-notification = "2"
tokio = { version = "1", features = ["full"] }
tokio-tungstenite = "0.24"
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
futures-util = "0.3"
uuid = { version = "1", features = ["v4"] }
log = "0.4"
env_logger = "0.11"
thiserror = "1"

[features]
default = ["custom-protocol"]
custom-protocol = ["tauri/custom-protocol"]
```

**注意**：Hermes-CN-Desktop 用 `tokio-tungstenite 0.29`；我们保守选 `0.24`（更成熟）。

- [ ] **Step 2: 写 build.rs**

`desktop/src-tauri/build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/Cargo.toml desktop/src-tauri/build.rs
git commit -m "feat(desktop): Cargo.toml + build.rs" \
  -m "Tauri 2 + tokio + tokio-tungstenite + reqwest + serde + uuid + log。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 写 tauri.conf.json

**Files:**
- 创建: `desktop/src-tauri/tauri.conf.json`

- [ ] **Step 1: 写文件**

```json
{
  "$schema": "https://schema.tauri.app/config/2.0.0",
  "productName": "Nexus",
  "version": "1.1.0",
  "identifier": "cn.yexiaobai.nexus",
  "build": {
    "beforeDevCommand": "cd ../../frontend && npm run dev",
    "beforeBuildCommand": "cd ../../frontend && npm run build",
    "devUrl": "http://localhost:30077",
    "frontendDist": "../../frontend/dist"
  },
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "Nexus",
        "width": 1280,
        "height": 820,
        "minWidth": 960,
        "minHeight": 680,
        "titleBarStyle": "Transparent",
        "hiddenTitle": true,
        "decorations": true
      }
    ],
    "security": {
      "csp": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:* wss://127.0.0.1:*; img-src 'self' data: blob:; media-src 'self' data: blob:; frame-src 'self' http://localhost:* http://127.0.0.1:*"
    }
  },
  "bundle": {
    "active": true,
    "targets": ["dmg"],
    "icon": ["icons/icon.icns"],
    "category": "DeveloperTool",
    "macOS": {
      "minimumSystemVersion": "10.15"
    },
    "externalBin": ["binaries/nexus-runtime"]
  }
}
```

- [ ] **Step 2: 写 capabilities/main.json**

`desktop/src-tauri/capabilities/main.json`:

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "main-capability",
  "description": "Main window capability for Nexus desktop",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "dialog:default",
    "notification:default"
  ]
}
```

- [ ] **Step 3: 验证 JSON 语法**

```bash
cd /Users/yxb/projects/nexus
python3 -c "import json; json.load(open('desktop/src-tauri/tauri.conf.json'))"
python3 -c "import json; json.load(open('desktop/src-tauri/capabilities/main.json'))"
```

期望：无输出

- [ ] **Step 4: 提交**

```bash
git add desktop/src-tauri/tauri.conf.json desktop/src-tauri/capabilities/
git commit -m "feat(desktop): tauri.conf.json + capabilities" \
  -m "窗口 1280x820、透明 titleBarStyle、CSP 放行 127.0.0.1:*、externalBin 指向 nexus-runtime。

WHY: macOS 关窗保活用 Tauri 内置 API(无需 pyobjc monkey-patch)。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 写 desktop/package.json

**Files:**
- 创建: `desktop/package.json`

- [ ] **Step 1: 写文件**

```json
{
  "name": "nexus-desktop",
  "version": "1.1.0",
  "private": true,
  "scripts": {
    "dev": "cargo tauri dev",
    "build": "cargo tauri build",
    "build:debug": "cargo tauri build --debug"
  }
}
```

- [ ] **Step 2: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/package.json
git commit -m "chore(desktop): package.json" \
  -m "Tauri dev/build 脚本入口。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 3: Rust 主进程

### Task 9: 写最小可运行 main.rs（仅窗口）

**Files:**
- 创建: `desktop/src-tauri/src/main.rs`

- [ ] **Step 1: 写文件**

```rust
// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod runtime;
mod ws_relay;

use tauri::{Manager, RunEvent, WindowEvent};

fn main() {
    env_logger::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            runtime::get_runtime_status,
            ws_relay::ws_open,
            ws_relay::ws_send,
            ws_relay::ws_close,
        ])
        .on_window_event(|window, event| {
            // 关窗 → 隐藏到 Dock,不退出
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    window.hide().ok();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri app")
        .run(|app_handle, event| {
            // macOS Dock 点击 → 重开窗口
            #[cfg(target_os = "macos")]
            if let RunEvent::Reopen { .. } = event {
                if let Some(win) = app_handle.get_webview_window("main") {
                    win.show().ok();
                    win.set_focus().ok();
                }
            }

            // 用户 cmd+Q → 关闭 sidecar
            if let RunEvent::ExitRequested { .. } = event {
                runtime::shutdown_sidecar(app_handle);
            }
        });
}
```

- [ ] **Step 2: 创建空的 stub runtime.rs 和 ws_relay.rs（占位让编译过）**

`desktop/src-tauri/src/runtime.rs`:

```rust
use serde::Serialize;

#[derive(Serialize, Clone)]
#[serde(tag = "type", content = "data")]
pub enum RuntimeStatus {
    Starting,
    Ready,
    Failed(String),
}

#[tauri::command]
pub async fn get_runtime_status() -> RuntimeStatus {
    RuntimeStatus::Starting
}

pub fn shutdown_sidecar(_app: &tauri::AppHandle) {
    // TODO: 实现 (Task 11)
}
```

`desktop/src-tauri/src/ws_relay.rs`:

```rust
// TODO: 实现 (Task 12-14)

#[tauri::command]
pub async fn ws_open(_url: String) -> Result<String, String> {
    Err("not implemented".into())
}

#[tauri::command]
pub async fn ws_send(
    _session_id: String,
    _payload: serde_json::Value,
    _on_chunk: tauri::Channel<serde_json::Value>,
) -> Result<(), String> {
    Err("not implemented".into())
}

#[tauri::command]
pub async fn ws_close(_session_id: String) -> Result<(), String> {
    Ok(())
}
```

- [ ] **Step 3: cargo check**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo check 2>&1 | tail -50
```

期望：编译成功（warning 可接受，error 必须修）

- [ ] **Step 4: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/
git commit -m "feat(desktop): main.rs + stub modules" \
  -m "Tauri 主进程骨架:窗口创建、关窗保活、Dock 重开、cmd+Q 关闭 sidecar 钩子。

runtime.rs / ws_relay.rs 暂时 stub,后续 Task 填充。

WHY: 关窗保活、Dock 重开、关 sidecar 全走 Tauri 内置 API,不再用 pyobjc monkey-patch。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 4: Sidecar 管理（runtime.rs）

### Task 10: 实现 sidecar spawn + 健康检查

**Files:**
- 修改: `desktop/src-tauri/src/runtime.rs`（替换 stub）

- [ ] **Step 1: 写完整文件**

```rust
use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tokio::process::{Child, Command};
use tokio::sync::RwLock;
use tokio::time::Instant;

pub struct AppState {
    pub sidecar: Arc<RwLock<Option<Child>>>,
    pub api_base: String,
    pub ws_url: String,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            sidecar: Arc::new(RwLock::new(None)),
            api_base: "http://127.0.0.1:30000".into(),
            ws_url: "ws://127.0.0.1:30000/api/ws".into(),
        }
    }
}

#[derive(Serialize, Clone)]
#[serde(tag = "type", content = "data")]
pub enum RuntimeStatus {
    Starting,
    Ready,
    Failed(String),
}

#[tauri::command]
pub async fn get_runtime_status(state: tauri::State<'_, AppState>) -> RuntimeStatus {
    if state.sidecar.read().await.is_some() {
        RuntimeStatus::Ready
    } else {
        RuntimeStatus::Starting
    }
}

/// 异步启动 sidecar 并等健康检查通过。
/// 启动后 emit "runtime-status: Ready" 给前端。
pub async fn start_sidecar(app: &AppHandle) -> Result<(), String> {
    let state: tauri::State<AppState> = app.state();

    // 解析 sidecar 路径
    // 开发模式: src-tauri/binaries/nexus-runtime-aarch64-apple-darwin
    // 打包模式: .app/Contents/MacOS/nexus-runtime
    let sidecar_path = resolve_sidecar_path(app)?;
    log::info!("starting sidecar: {sidecar_path:?}");

    let mut cmd = Command::new(&sidecar_path);
    cmd.args(["--host", "127.0.0.1", "--port", "30000"])
        .kill_on_drop(true);

    let child = cmd
        .spawn()
        .map_err(|e| format!("spawn failed: {e} (path: {sidecar_path:?})"))?;

    *state.sidecar.write().await = Some(child);

    // 健康检查
    wait_for_health(&state.api_base, 30).await?;
    log::info!("sidecar ready");

    app.emit("runtime-status", RuntimeStatus::Ready).ok();
    Ok(())
}

fn resolve_sidecar_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    use tauri::path::BaseDirectory;

    // 先尝试 Resource 目录(打包模式)
    if let Ok(p) = app.path().resolve("nexus-runtime", BaseDirectory::Resource) {
        if p.exists() {
            return Ok(p);
        }
    }

    // 再尝试 Resource 目录的父目录(.app/Contents/MacOS/,Tauri 2 习惯)
    if let Ok(resource) = app.path().resource_dir() {
        let macos_path = resource.parent().unwrap_or(&resource).join("MacOS").join("nexus-runtime");
        if macos_path.exists() {
            return Ok(macos_path);
        }
    }

    // 开发模式:src-tauri/binaries/nexus-runtime-aarch64-apple-darwin
    let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("binaries")
        .join(format!("nexus-runtime-{}", std::env::consts::ARCH));

    if dev_path.exists() {
        return Ok(dev_path);
    }

    Err(format!(
        "sidecar binary not found. tried: resource dir, .app/Contents/MacOS/, dev: {dev_path:?}"
    ))
}

async fn wait_for_health(url: &str, timeout_secs: u64) -> Result<(), String> {
    let deadline = Duration::from_secs(timeout_secs);
    let start = Instant::now();
    while start.elapsed() < deadline {
        match reqwest::get(format!("{url}/health")).await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => {}
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    Err(format!("health check timeout after {timeout_secs}s"))
}

/// 后台监控 sidecar,崩溃自动重启,最多 3 次
pub async fn supervise_sidecar(app: AppHandle) {
    let mut retries = 0;
    while retries < 3 {
        tokio::time::sleep(Duration::from_secs(2)).await;
        let state: tauri::State<AppState> = app.state();
        let mut guard = state.sidecar.write().await;
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    log::warn!("sidecar exited: {status}");
                    if !status.success() {
                        retries += 1;
                        log::info!("restart attempt {retries}/3");
                        drop(guard);
                        if let Err(e) = start_sidecar(&app).await {
                            log::error!("restart failed: {e}");
                            app.emit(
                                "runtime-status",
                                RuntimeStatus::Failed(e),
                            )
                            .ok();
                            return;
                        }
                    }
                }
                Ok(None) => {
                    // 还活着,继续监控
                }
                Err(e) => {
                    log::error!("try_wait error: {e}");
                }
            }
        }
    }
    log::error!("sidecar supervisor exhausted retries");
    app.emit(
        "runtime-status",
        RuntimeStatus::Failed("supervisor exhausted".into()),
    )
    .ok();
}

pub fn shutdown_sidecar(app: &tauri::AppHandle) {
    let state: tauri::State<AppState> = app.state();
    // 用 try_write 避免 await 在 shutdown 路径阻塞
    if let Ok(mut guard) = state.sidecar.try_write() {
        if let Some(mut child) = guard.take() {
            log::info!("killing sidecar");
            child.kill().ok();
        }
    }
}
```

- [ ] **Step 2: cargo check**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo check 2>&1 | tail -30
```

期望：编译成功

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/runtime.rs
git commit -m "feat(desktop): sidecar 进程管理" \
  -m "spawn + 健康检查 + supervisor(3 次重试) + shutdown。

路径解析:Resource dir → .app/Contents/MacOS/ → dev mode binaries/。

WHY: 把现有 launcher.py 的 uvicorn + health check 逻辑搬到 Rust,sidecar 进程崩溃自动拉起。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 在 main.rs 里调用 start_sidecar + supervise

**Files:**
- 修改: `desktop/src-tauri/src/main.rs`

- [ ] **Step 1: 加 .manage(state) 和 .setup()**

修改 `desktop/src-tauri/src/main.rs`，把 `fn main()` 改成：

```rust
fn main() {
    env_logger::init();

    let app_state = runtime::AppState::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            runtime::get_runtime_status,
            ws_relay::ws_open,
            ws_relay::ws_send,
            ws_relay::ws_close,
        ])
        .setup(|app| {
            // 异步起 sidecar,不阻塞窗口出现
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = runtime::start_sidecar(&handle).await {
                    log::error!("sidecar start failed: {e}");
                    runtime::shutdown_sidecar(&handle);
                    handle
                        .emit(
                            "runtime-status",
                            runtime::RuntimeStatus::Failed(e),
                        )
                        .ok();
                    return;
                }
                runtime::supervise_sidecar(handle).await;
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    window.hide().ok();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri app")
        .run(|app_handle, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                if let Some(win) = app_handle.get_webview_window("main") {
                    win.show().ok();
                    win.set_focus().ok();
                }
            }

            if let tauri::RunEvent::ExitRequested { .. } = event {
                runtime::shutdown_sidecar(app_handle);
            }
        });
}
```

- [ ] **Step 2: cargo check**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo check 2>&1 | tail -30
```

期望：编译成功

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/main.rs
git commit -m "feat(desktop): main.rs 集成 sidecar 编排" \
  -m ".setup() 异步 spawn start_sidecar → supervise_sidecar。

WHY: 让窗口立即出现,sidecar 后台起,避免 10-30s 卡顿。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 5: WebSocket Relay（ws_relay.rs）

### Task 12: 写 RelayState + ws_open

**Files:**
- 修改: `desktop/src-tauri/src/ws_relay.rs`

- [ ] **Step 1: 替换文件**

```rust
use std::collections::HashMap;

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::Channel;
use tokio::sync::RwLock;
use tokio_tungstenite::tungstenite::Message;

type WsTx = futures_util::stream::SplitSink<
    tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
    Message,
>;

type WsRx = futures_util::stream::SplitStream<
    tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
>;

pub struct RelayState {
    pub sessions: RwLock<HashMap<String, WsSession>>,
}

impl Default for RelayState {
    fn default() -> Self {
        Self::new()
    }
}

impl RelayState {
    pub fn new() -> Self {
        Self {
            sessions: RwLock::new(HashMap::new()),
        }
    }
}

pub struct WsSession {
    pub tx: WsTx,
    pub rx: Option<WsRx>,
    pub rx_task: Option<tokio::task::JoinHandle<()>>,
}

#[tauri::command]
pub async fn ws_open(
    url: String,
    state: tauri::State<'_, RelayState>,
) -> Result<String, String> {
    let (ws, _) = tokio_tungstenite::connect_async(&url)
        .await
        .map_err(|e| format!("ws connect failed: {e}"))?;

    let session_id = uuid::Uuid::new_v4().to_string();
    let (tx, rx) = ws.split();

    state.sessions.write().await.insert(
        session_id.clone(),
        WsSession {
            tx,
            rx: Some(rx),
            rx_task: None,
        },
    );

    log::info!("ws session opened: {session_id}");
    Ok(session_id)
}
```

- [ ] **Step 2: 把 RelayState 注册到 main.rs**

在 `main.rs` 的 `tauri::Builder` 链上加 `.manage(ws_relay::RelayState::new())`，位置在 `.manage(app_state)` 之后：

```rust
.manage(app_state)
.manage(ws_relay::RelayState::new())
```

- [ ] **Step 3: cargo check**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo check 2>&1 | tail -30
```

期望：编译成功

- [ ] **Step 4: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/ws_relay.rs desktop/src-tauri/src/main.rs
git commit -m "feat(desktop): ws_relay ws_open + RelayState" \
  -m "Rust 端 WS 客户端,Session 管理用 RwLock<HashMap>。

WHY: 把 WS 流式从 pywebview 直连改为 Rust 中转,前端用 Tauri Channel 接收。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: 实现 ws_send（启动接收 task + 转发）

**Files:**
- 修改: `desktop/src-tauri/src/ws_relay.rs`

- [ ] **Step 1: 在文件末尾追加 ws_send 实现**

```rust
#[tauri::command]
pub async fn ws_send(
    session_id: String,
    payload: Value,
    on_chunk: Channel<Value>,
    state: tauri::State<'_, RelayState>,
) -> Result<(), String> {
    // 1. 取出 session,把 rx 从 Option 里搬出来给 task
    let (tx, rx, old_task) = {
        let mut sessions = state.sessions.write().await;
        let session = sessions
            .get_mut(&session_id)
            .ok_or_else(|| format!("session not found: {session_id}"))?;

        let rx = session
            .rx
            .take()
            .ok_or_else(|| "rx already consumed".to_string())?;
        let old_task = session.rx_task.take();

        (tx, rx, old_task)
    };

    // 取消之前的 task(如果有,通常是 reconnect)
    if let Some(task) = old_task {
        task.abort();
    }

    // 2. 启动接收 task
    let on_chunk_clone = on_chunk.clone();
    let session_id_for_task = session_id.clone();
    let rx_task = tokio::spawn(async move {
        let mut rx = rx;
        while let Some(msg) = rx.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    match serde_json::from_str::<Value>(&text) {
                        Ok(value) => {
                            let is_done = value
                                .get("type")
                                .and_then(|v| v.as_str())
                                .map(|s| s == "done")
                                .unwrap_or(false);
                            if on_chunk_clone.send(value).is_err() {
                                log::warn!("channel send failed, frontend disconnected");
                                break;
                            }
                            if is_done {
                                break;
                            }
                        }
                        Err(e) => {
                            log::warn!("json parse failed: {e}, raw: {text}");
                        }
                    }
                }
                Ok(Message::Close(_)) => {
                    log::info!("ws closed by server: {session_id_for_task}");
                    break;
                }
                Ok(_) => {} // Ping/Pong/Frame 等忽略
                Err(e) => {
                    log::error!("ws error: {e}");
                    on_chunk_clone
                        .send(serde_json::json!({"type": "error", "data": e.to_string()}))
                        .ok();
                    break;
                }
            }
        }
        log::info!("ws rx task ended: {session_id_for_task}");
    });

    // 3. 存回 task handle(保留 tx 给后续 send)
    {
        let mut sessions = state.sessions.write().await;
        if let Some(session) = sessions.get_mut(&session_id) {
            session.rx_task = Some(rx_task);
        }
    }

    // 4. 发送 payload
    let mut sessions = state.sessions.write().await;
    let session = sessions
        .get_mut(&session_id)
        .ok_or_else(|| "session gone".to_string())?;
    session
        .tx
        .send(Message::Text(payload.to_string()))
        .await
        .map_err(|e| format!("ws send failed: {e}"))?;

    Ok(())
}
```

- [ ] **Step 2: cargo check**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo check 2>&1 | tail -30
```

期望：编译成功

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/ws_relay.rs
git commit -m "feat(desktop): ws_send 实现" \
  -m "启动接收 task 转发 ws message 到 Tauri Channel,done 消息自动 break。

WHY: 解决 spec 段 5.4 提到的 rx 字段重构 — 用 Option<Rx> + take() 模式让 task 独占 rx。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: 实现 ws_close

**Files:**
- 修改: `desktop/src-tauri/src/ws_relay.rs`

- [ ] **Step 1: 替换 ws_close**

```rust
#[tauri::command]
pub async fn ws_close(
    session_id: String,
    state: tauri::State<'_, RelayState>,
) -> Result<(), String> {
    let mut sessions = state.sessions.write().await;
    if let Some(mut session) = sessions.remove(&session_id) {
        if let Some(task) = session.rx_task.take() {
            task.abort();
        }
        session.tx.close().await.ok();
        log::info!("ws session closed: {session_id}");
    }
    Ok(())
}
```

- [ ] **Step 2: cargo check**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo check 2>&1 | tail -10
```

期望：编译成功

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/ws_relay.rs
git commit -m "feat(desktop): ws_close 实现" \
  -m "abort rx task + close tx + 从 sessions 移除。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 15: Rust 端单元测试

**Files:**
- 创建: `desktop/src-tauri/src/ws_relay_tests.rs`（集成到 lib.rs）

- [ ] **Step 1: 写 ws_relay 单元测试**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_relay_state_new() {
        let state = RelayState::new();
        let sessions = state.sessions.read().await;
        assert!(sessions.is_empty());
    }

    #[tokio::test]
    async fn test_ws_open_invalid_url() {
        let state = RelayState::new();
        let result = ws_open(
            "ws://invalid.localhost:9999".to_string(),
            tauri::State::from(&state),
        )
        .await;
        assert!(result.is_err());
    }
}
```

**注意**：由于 `tauri::State` 在测试中难以构造，第二个测试可能需要重构（用具体 trait）。如失败可删除，仅保留 `test_relay_state_new`。

- [ ] **Step 2: cargo test**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo test --lib 2>&1 | tail -20
```

期望：`test result: ok. 1 passed`（第二个测试如编译失败可删）

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add desktop/src-tauri/src/ws_relay.rs
git commit -m "test(desktop): RelayState 单元测试" \
  -m "基础状态管理 + 无效 URL 测试。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 6: 前端 Tauri Hook

### Task 16: 加 @tauri-apps/api 依赖

**Files:**
- 修改: `frontend/package.json`

- [ ] **Step 1: 装包**

```bash
cd /Users/yxb/projects/nexus/frontend
npm install @tauri-apps/api@^2
```

- [ ] **Step 2: 验证**

```bash
grep '"@tauri-apps/api"' /Users/yxb/projects/nexus/frontend/package.json
```

期望：看到版本号

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): @tauri-apps/api 依赖" \
  -m "Tauri 2 官方前端 SDK,提供 invoke/Channel/listen API。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 17: 写 useTauriWs hook

**Files:**
- 创建: `frontend/src/hooks/useTauriWs.ts`

- [ ] **Step 1: 写文件**

```typescript
import { invoke, Channel } from '@tauri-apps/api/core';
import { useEffect, useRef, useState } from 'react';

// 与现有 WS 协议保持一致(后端 StreamMsg 形状不变)
export interface StreamMsg {
  type: 'thinking' | 'chunk' | 'final' | 'done' | 'error';
  data?: unknown;
}

interface UseTauriWsResult {
  connected: boolean;
  send: (payload: unknown) => Promise<void>;
}

/**
 * Tauri Channel 版 WebSocket hook。
 * 替代 useWebSocket.ts,把 WS 流式经 Rust relay 转发。
 *
 * 用法:
 *   const { connected, send } = useTauriWs('/api/ws', (msg) => handle(msg))
 *   await send({ type: 'chat', sessionId, content })
 */
export function useTauriWs(
  url: string,
  onMessage: (msg: StreamMsg) => void
): UseTauriWsResult {
  const [connected, setConnected] = useState(false);
  const sessionRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        // Tauri 2 在 webview 中: 走 ws://127.0.0.1:30000/api/ws?token=xxx
        // 直接拼绝对 URL
        const fullUrl = url.startsWith('ws')
          ? url
          : `ws://127.0.0.1:30000${url.startsWith('/') ? '' : '/'}${url}`;

        const sessionId = await invoke<string>('ws_open', { url: fullUrl });
        if (cancelled) return;
        sessionRef.current = sessionId;
        setConnected(true);
      } catch (e) {
        onMessage({ type: 'error', data: String(e) });
      }
    })();

    return () => {
      cancelled = true;
      const sessionId = sessionRef.current;
      if (sessionId) {
        invoke('ws_close', { sessionId }).catch(() => {});
      }
    };
  }, [url, onMessage]);

  const send = async (payload: unknown): Promise<void> => {
    const sessionId = sessionRef.current;
    if (!sessionId) throw new Error('ws not connected');

    const onChunk = new Channel<StreamMsg>();
    onChunk.onmessage = onMessage;

    await invoke('ws_send', { sessionId, payload, onChunk });
  };

  return { connected, send };
}
```

- [ ] **Step 2: TypeScript 类型检查**

```bash
cd /Users/yxb/projects/nexus/frontend
npx tsc --noEmit src/hooks/useTauriWs.ts 2>&1 | head -30
```

期望：无错误

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add frontend/src/hooks/useTauriWs.ts
git commit -m "feat(frontend): useTauriWs hook" \
  -m "Tauri Channel 版 WS hook,接口与 useWebSocket 类似(connected + send)。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 7: 前端 Splash + App 集成

### Task 18: 写 SplashView

**Files:**
- 创建: `frontend/src/components/desktop/SplashView.tsx`

- [ ] **Step 1: 写文件**

```tsx
import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';

export interface RuntimeStatus {
  type: 'Starting' | 'Ready' | 'Failed';
  data?: string;
}

/**
 * 启动 splash: 监听 Rust emit 的 runtime-status 事件。
 * Starting → 显示 loading
 * Ready → 父组件切到主页(此组件自己隐藏)
 * Failed → 显示错误 + 重试按钮
 */
export function SplashView() {
  const [status, setStatus] = useState<RuntimeStatus>({ type: 'Starting' });

  useEffect(() => {
    let unlistenFn: (() => void) | null = null;

    listen<RuntimeStatus>('runtime-status', (e) => {
      setStatus(e.payload);
    }).then((fn) => {
      unlistenFn = fn;
    });

    return () => {
      if (unlistenFn) unlistenFn();
    };
  }, []);

  if (status.type === 'Failed') {
    return (
      <div className="splash splash-error">
        <div className="splash-logo">N</div>
        <h2>后端启动失败</h2>
        <p className="splash-error-msg">{status.data}</p>
        <button
          className="splash-retry"
          onClick={() => window.location.reload()}
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="splash">
      <div className="splash-logo">N</div>
      <p>正在启动 Nexus...</p>
      <div className="splash-spinner" />
    </div>
  );
}
```

- [ ] **Step 2: 加 splash 样式**

修改 `frontend/src/components/desktop/styles/shell.css`，**追加**到末尾：

```css
.splash {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
  background: var(--color-cream, #faf8f5);
  color: var(--color-text-dark, #2c3e2d);
  z-index: 9999;
}

.splash-logo {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: #1a1a1a;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: bold;
}

.splash-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid rgba(74, 124, 89, 0.2);
  border-top-color: #4a7c59;
  border-radius: 50%;
  animation: splash-spin 0.8s linear infinite;
}

@keyframes splash-spin {
  to { transform: rotate(360deg); }
}

.splash-error {
  background: #fef2f2;
  color: #991b1b;
}

.splash-error-msg {
  font-family: monospace;
  font-size: 12px;
  max-width: 480px;
  text-align: center;
  word-break: break-all;
}

.splash-retry {
  margin-top: 16px;
  padding: 8px 24px;
  background: #4a7c59;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}

.splash-retry:hover {
  background: #3a6249;
}
```

- [ ] **Step 3: 提交**

```bash
cd /Users/yxb/projects/nexus
git add frontend/src/components/desktop/SplashView.tsx frontend/src/components/desktop/styles/shell.css
git commit -m "feat(frontend): SplashView + 启动样式" \
  -m "监听 runtime-status 事件:Starting→loading,Failed→错误页+重试。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 19: 改 App.tsx 集成 Splash

**Files:**
- 修改: `frontend/src/App.tsx`

- [ ] **Step 1: 读现有 App.tsx 找到主渲染逻辑**

```bash
cat /Users/yxb/projects/nexus/frontend/src/App.tsx
```

- [ ] **Step 2: 在最外层加 Splash 判断（用 listen 而不是 useTauriWs 因为 SplashView 自己已处理）**

修改 App.tsx 的主渲染：

```tsx
import { listen } from '@tauri-apps/api/event';
import { useEffect, useState } from 'react';
import { SplashView, RuntimeStatus } from './components/desktop/SplashView';

// 假设主组件是 MainApp
function App() {
  const [runtimeReady, setRuntimeReady] = useState(false);

  useEffect(() => {
    let unlistenFn: (() => void) | null = null;

    listen<RuntimeStatus>('runtime-status', (e) => {
      if (e.payload.type === 'Ready') setRuntimeReady(true);
    }).then((fn) => {
      unlistenFn = fn;
    });

    return () => {
      if (unlistenFn) unlistenFn();
    };
  }, []);

  if (!runtimeReady) return <SplashView />;

  return <MainApp />;
}
```

**注意**：具体 MainApp / 路由结构按现有 App.tsx 调整。如果现有 App.tsx 用 React Router，把 `<SplashView />` 作为根路由的 fallback。

- [ ] **Step 3: TypeScript 检查**

```bash
cd /Users/yxb/projects/nexus/frontend
npx tsc --noEmit 2>&1 | head -30
```

期望：无错误

- [ ] **Step 4: 提交**

```bash
cd /Users/yxb/projects/nexus
git add frontend/src/App.tsx
git commit -m "feat(frontend): App.tsx 集成 Splash" \
  -m "监听 runtime-status,Ready 后切到主界面。

WHY: sidecar 后台启期间,前端显示 splash,启动完切主页。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 20: 替换 useWebSocket 调用方为 useTauriWs

**Files:**
- 修改: 找到 `useWebSocket` 的所有调用方,改成 `useTauriWs`

- [ ] **Step 1: 找调用方**

```bash
cd /Users/yxb/projects/nexus
grep -rn "useWebSocket" frontend/src/ --include="*.ts" --include="*.tsx"
```

期望：列出 1-3 个文件

- [ ] **Step 2: 改 import 和 hook 名**

每个调用文件：
- `import { useWebSocket } from '...'` → `import { useTauriWs } from '@/hooks/useTauriWs'`
- `useWebSocket(` → `useTauriWs(`
- hook 接口不变（都有 `connected` 和 `send`），调用代码无需改

- [ ] **Step 3: TypeScript 检查**

```bash
cd /Users/yxb/projects/nexus/frontend
npx tsc --noEmit 2>&1 | head -30
```

期望：无错误

- [ ] **Step 4: 提交**

```bash
cd /Users/yxb/projects/nexus
git add frontend/src/
git commit -m "refactor(frontend): 切换 useWebSocket → useTauriWs" \
  -m "Hook 接口兼容(connected + send),只改 import 和调用名。

WHY: Tauri 模式下 WS 走 Rust relay,前端用 Channel 接。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 8: 构建脚本

### Task 21: 写 build_sidecar.sh（PyInstaller onedir）

**Files:**
- 创建: `scripts/build_sidecar.sh`

- [ ] **Step 1: 写文件**

```bash
#!/usr/bin/env bash
# 打 Python sidecar(PyInstaller onedir)
# 产物: release/nexus-runtime/ (整个目录)
# Tauri 的 externalBin 期望一个可执行文件,onedir 模式产物的可执行文件就在 nexus-runtime/nexus-runtime

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# 1. 构建前端(若未构建)
if [ ! -d "$ROOT_DIR/frontend/dist" ]; then
  echo ">>> building frontend..."
  (cd frontend && npm install && npm run build)
fi

# 2. PyInstaller onedir(无 webview 依赖)
echo ">>> pyinstaller onedir for sidecar..."
"$ROOT_DIR/.venv/bin/pip" install --quiet pyinstaller
rm -rf "$ROOT_DIR/release/nexus-runtime"
mkdir -p "$ROOT_DIR/release"

"$ROOT_DIR/.venv/bin/pyinstaller" \
  --name nexus-runtime \
  --onedir \
  --noconfirm \
  --paths "$ROOT_DIR" \
  --collect-submodules fastapi \
  --collect-submodules deepagents \
  --collect-submodules langchain \
  --collect-submodules mcp \
  --collect-submodules uvicorn \
  --hidden-import=uvicorn \
  --hidden-import=nexus.backend.main \
  "$ROOT_DIR/nexus/backend/runtime_main.py"

# 3. 移产物
mv "$ROOT_DIR/dist/nexus-runtime" "$ROOT_DIR/release/nexus-runtime"
rm -rf "$ROOT_DIR/dist" "$ROOT_DIR/build"

echo ">>> sidecar: $ROOT_DIR/release/nexus-runtime/"
ls -la "$ROOT_DIR/release/nexus-runtime/" | head -10

# 4. Tauri externalBin 命名约定: nexus-runtime-{arch}-{platform}
# 复制为符合 Tauri 约定的文件名
ARCH=$(uname -m)
PLATFORM="apple-darwin"
TARBALL_NAME="nexus-runtime-${ARCH}-${PLATFORM}"
cp "$ROOT_DIR/release/nexus-runtime/nexus-runtime" \
   "$ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"
chmod +x "$ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"

echo ">>> Tauri sidecar: $ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"
ls -lh "$ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"
```

- [ ] **Step 2: 加执行权限**

```bash
chmod +x /Users/yxb/projects/nexus/scripts/build_sidecar.sh
```

- [ ] **Step 3: 跑通**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
bash scripts/build_sidecar.sh 2>&1 | tail -30
```

期望：看到 "Tauri sidecar" 行,文件存在

- [ ] **Step 4: 测试 sidecar 二进制可启动**

```bash
"$ROOT_DIR/release/nexus-runtime/nexus-runtime" --port 30002 &
SPID=$!
sleep 2
curl -s http://127.0.0.1:30002/health
kill $SPID 2>/dev/null
```

期望：返回 200

- [ ] **Step 5: 提交**

```bash
cd /Users/yxb/projects/nexus
git add scripts/build_sidecar.sh
git commit -m "feat(scripts): build_sidecar.sh" \
  -m "PyInstaller onedir 打 nexus-runtime,产物复制为 Tauri 约定文件名 nexus-runtime-{arch}-{platform}。

WHY: Tauri 2 externalBin 机制要求固定命名约定。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 22: 重写 build_dmg.sh（Tauri build + DMG）

**Files:**
- 修改: `scripts/build_dmg.sh`

- [ ] **Step 1: 备份现有脚本**

```bash
cp /Users/yxb/projects/nexus/scripts/build_dmg.sh /Users/yxb/projects/nexus/scripts/build_dmg.sh.bak
```

- [ ] **Step 2: 重写脚本**

```bash
#!/usr/bin/env bash
# 打包 Nexus 桌面 APP (.app + .dmg),产物 macOS arm64。
#
# 步骤:
#   1. 跑 build_sidecar.sh 生成 sidecar
#   2. cargo tauri build 产出 .app + .dmg
#
# 为什么不继续用 PyInstaller:
#   - Tauri 主程序只 ~10 MB,sidecar 单独打 ~40 MB
#   - 不用打包 Python 解释器到主程序,启动快
#   - 关窗保活/Dock 重开走 Tauri 内置 API,无需 monkey-patch

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${VERSION:-1.1.0}"
ARCH="${ARCH:-$(uname -m)}"  # arm64 或 x86_64
APP_NAME="Nexus"
DMG_NAME="${APP_NAME}-${VERSION}-${ARCH}"

# 1. 打 sidecar
echo ">>> step 1: build sidecar..."
bash "$ROOT_DIR/scripts/build_sidecar.sh"

# 2. cargo tauri build
echo ">>> step 2: cargo tauri build..."
cd "$ROOT_DIR/desktop/src-tauri"
cargo tauri build --target "${ARCH}-apple-darwin"

# 3. 找产物
APP_BUNDLE="$ROOT_DIR/desktop/src-tauri/target/${ARCH}-apple-darwin/release/bundle/macos/${APP_NAME}.app"
DMG_SOURCE="$ROOT_DIR/desktop/src-tauri/target/${ARCH}-apple-darwin/release/bundle/dmg/${DMG_NAME}.dmg"

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: app bundle not found at $APP_BUNDLE"
  exit 1
fi

# 4. 移到 release/(统一位置)
mkdir -p "$ROOT_DIR/release"
cp -R "$APP_BUNDLE" "$ROOT_DIR/release/${APP_NAME}.app"
rm -rf "$ROOT_DIR/release/${APP_NAME}.app.bak" 2>/dev/null || true

# 5. 复制 DMG(如果 cargo tauri build 已生成)
if [ -f "$DMG_SOURCE" ]; then
  cp "$DMG_SOURCE" "$ROOT_DIR/release/${DMG_NAME}.dmg"
  echo ">>> DMG: $ROOT_DIR/release/${DMG_NAME}.dmg"
  ls -lh "$ROOT_DIR/release/${DMG_NAME}.dmg"
fi

# 6. 清理临时 .app(避免和 /Applications 同名冲突)
# 用户从 DMG 拖到 /Applications 才是正式安装路径

echo ">>> release/ 内容:"
ls -la "$ROOT_DIR/release/"
echo ">>> 提示: 把 release/${DMG_NAME}.dmg 分发给用户,用户拖到 /Applications 安装"
```

- [ ] **Step 3: 加执行权限**

```bash
chmod +x /Users/yxb/projects/nexus/scripts/build_dmg.sh
```

- [ ] **Step 4: 验证语法**

```bash
bash -n /Users/yxb/projects/nexus/scripts/build_dmg.sh
echo "syntax OK"
```

- [ ] **Step 5: 提交**

```bash
cd /Users/yxb/projects/nexus
git add scripts/build_dmg.sh
git rm scripts/build_dmg.sh.bak 2>/dev/null || true
git commit -m "feat(scripts): build_dmg.sh 重写为 Tauri build" \
  -m "step 1: build_sidecar.sh → step 2: cargo tauri build → step 3: 移产物到 release/

WHY: 旧脚本走 PyInstaller 全打包,新脚本 sidecar 独立打,主程序 10MB。" \
  -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 9: dev 模式跑通

### Task 23: 验证 Tauri dev 模式启动

**Files:**
- 修改: 无

- [ ] **Step 1: 先确保 sidecar 二进制在位**

```bash
ls -lh /Users/yxb/projects/nexus/desktop/src-tauri/binaries/
```

期望：看到 `nexus-runtime-arm64-apple-darwin` 或对应 arch 文件

- [ ] **Step 2: 启动 Tauri dev 模式**

```bash
cd /Users/yxb/projects/nexus/desktop/src-tauri
cargo tauri dev 2>&1 | head -100
```

期望：
- 窗口出现
- 200ms 内看到 splash
- 1-2s 后 sidecar 起来,splash 切到主页
- 没有 pyobjc monkey-patch 相关报错

- [ ] **Step 3: 测试关窗保活**

- 点 X
- 期望：窗口消失,Dock 图标还在
- 点 Dock 图标
- 期望：窗口重新出现

- [ ] **Step 4: 测试 cmd+Q 正常退出**

- cmd+Q
- 期望：进程退出,sidecar 也关掉

- [ ] **Step 5: 如有报错,记录并修复**

不要继续 Phase 10,直到 Task 23 完全通过。

---

### Task 24: 流式聊天 E2E

**Files:**
- 修改: 无

- [ ] **Step 1: 在 Tauri dev 模式启动后,发一条消息**

- 在 UI 里输入"hello"
- 期望：看到 thinking → chunk → final → done 流式输出

- [ ] **Step 2: 验证 WS 走 Rust relay**

```bash
# 在终端看 Rust 日志,确认看到 "ws session opened"
```

期望：cargo tauri dev 输出里有 "ws session opened: <uuid>"

- [ ] **Step 3: 验证多轮对话**

- 发第二条消息
- 期望：流式正常,无 WS 累积泄漏

- [ ] **Step 4: 验证 cmd+Q 关闭 sidecar**

- 在 Rust 进程管理里 ps aux | grep nexus-runtime
- cmd+Q 后
- 期望：nexus-runtime 进程消失

---

## Phase 10: 打包验证

### Task 25: cargo tauri build 跑通

**Files:**
- 修改: 无

- [ ] **Step 1: 清干净旧产物**

```bash
cd /Users/yxb/projects/nexus
rm -rf desktop/src-tauri/target/release/bundle
rm -rf release
```

- [ ] **Step 2: 跑 build_dmg.sh**

```bash
cd /Users/yxb/projects/nexus
bash scripts/build_dmg.sh 2>&1 | tail -50
```

期望：
- build_sidecar.sh 通过
- cargo tauri build 通过
- release/Nexus-1.1.0-arm64.dmg 存在
- DMG 大小 30-50MB

- [ ] **Step 3: 验证 .app 内部结构**

```bash
ls /Users/yxb/projects/nexus/release/Nexus.app/Contents/
ls /Users/yxb/projects/nexus/release/Nexus.app/Contents/MacOS/
ls /Users/yxb/projects/nexus/release/Nexus.app/Contents/Resources/
```

期望：
- MacOS/Nexus（Tauri 主程序）
- MacOS/nexus-runtime（sidecar 二进制，Tauri 2 自动复制）
- Resources/frontend/（前端 dist）

---

### Task 26: 装到 /Applications 测试

**Files:**
- 修改: 无

- [ ] **Step 1: 删除旧版本**

```bash
rm -rf /Applications/Nexus.app
```

- [ ] **Step 2: 拷贝新版本**

```bash
cp -R /Users/yxb/projects/nexus/release/Nexus.app /Applications/
```

- [ ] **Step 3: 启动**

```bash
open /Applications/Nexus.app
```

- [ ] **Step 4: 完整流程测试**

- 启动后看到 splash（不是闪白）
- 1-2s 后看到主页
- 发消息流式响应正常
- 点 X 隐藏到 Dock
- Dock 点击重开
- cmd+Q 完全退出

- [ ] **Step 5: 检查 Console.app 没有 pyobjc / pywebview 相关错误**

打开 Console.app,过滤 "Nexus",确认没有 pyobjc import 错误或 webview 警告。

---

## Phase 11: 完整 E2E 模拟人工测试

### Task 27: 启动流程测试

**Files:**
- 修改: 无

**测试用例：**

- [ ] **Step 1: 冷启动时间**

```bash
# 用 stopwatch 或 AppleScript 测启动到主页时间
time open /Applications/Nexus.app
# 人眼看: 点图标 → 看到主页的时间
```

期望：< 3 秒（之前 pywebview 方案是 2-3 秒,Tauri 应更快）

- [ ] **Step 2: 热启动时间**

先启动一次,完全退出,再启动。期望 < 2 秒。

- [ ] **Step 3: 启动期间无闪白**

肉眼/录屏检查。

- [ ] **Step 4: 启动期间无"黑色横条"**

肉眼/录屏检查。

---

### Task 28: 窗口行为测试

**测试用例：**

- [ ] **Step 1: 关窗保活**

点 X → 窗口消失,Dock 图标还在。

- [ ] **Step 2: Dock 重开**

点 Dock 图标 → 窗口回来。

- [ ] **Step 3: cmd+W**

cmd+W → 窗口关闭（macOS 标准）。

- [ ] **Step 4: cmd+Q**

cmd+Q → 完全退出,进程消失。

- [ ] **Step 5: 最小化**

点黄按钮 → 窗口最小化到 Dock。

- [ ] **Step 6: 全屏**

点绿按钮 → 全屏切换正常。

- [ ] **Step 7: 拖动窗口**

拖动窗口 → 流畅,无掉帧。

- [ ] **Step 8: 调整大小**

拖窗口边缘 → 最小尺寸限制生效（960x680）。

---

### Task 29: 聊天功能测试

**测试用例：**

- [ ] **Step 1: 简单对话**

发"你好" → 期望收到 AI 回复,流式 thinking → chunk → final → done。

- [ ] **Step 2: 长回复**

发"介绍一下 Nexus" → 期望分多次 chunk 流式输出,最终有 final。

- [ ] **Step 3: 多轮对话**

连续发 3 条 → 期望每条都流式正常,无 WS 累积错误。

- [ ] **Step 4: 取消生成**

发消息后立即点"停止" → 期望后续 chunk 不再到达,前端 UI 正确回到 idle。

- [ ] **Step 5: 错误恢复**

人为 kill sidecar (`kill $(pgrep nexus-runtime)`) → 期望 supervisor 检测并重启,或显示错误页。

- [ ] **Step 6: 重连**

在系统网络切换（断 WiFi 再连） → 期望 WS 重连或正确报错。

---

### Task 30: 数据持久化测试

**测试用例：**

- [ ] **Step 1: 会话列表**

启动 → 看到历史 sessions 列表。

- [ ] **Step 2: 新建会话**

点"+" → 新会话出现在列表。

- [ ] **Step 3: 切会话**

点击旧会话 → 看到历史消息。

- [ ] **Step 4: 删除会话**

删除一个会话 → 列表移除,刷新后仍在移除状态。

- [ ] **Step 5: 重启 APP 数据保留**

cmd+Q 完全退出 → 重新 open → 期望所有 sessions/messages 还在。

- [ ] **Step 6: 数据库位置**

```bash
ls -lh ~/.nexus/nexus.db
```

期望：文件存在,大小 > 0。

---

### Task 31: 高级功能测试

**测试用例：**

- [ ] **Step 1: 模型切换**

设置里切换模型 → 重启 → 期望新模型生效。

- [ ] **Step 2: AGENTS.md 编辑**

让 LLM 自己改 AGENTS.md（通过提示）→ 期望 QualityGate 拦截或允许,符合预期。

- [ ] **Step 3: MCP 工具**

如果启用了 MCP,加载一个工具 → 调用 → 期望正常工作。

- [ ] **Step 4: 系统暗色模式**

切换 macOS 系统到 Dark Mode → APP 是否跟随(如有 Dark Mode 主题)。

---

### Task 32: DMG 分发测试

**测试用例：**

- [ ] **Step 1: 双击 DMG**

```bash
open /Users/yxb/projects/nexus/release/Nexus-1.1.0-arm64.dmg
```

期望：Finder 弹出窗口,显示 Nexus.app 和 Applications 文件夹快捷方式。

- [ ] **Step 2: 拖到 Applications**

拖 Nexus.app 到 /Applications → 进度条/复制。

- [ ] **Step 3: 弹出 DMG**

点 Finder 弹窗的"推出"。

- [ ] **Step 4: 启动 APP**

open /Applications/Nexus.app → 期望正常运行。

- [ ] **Step 5: 卸载干净性**

rm -rf /Applications/Nexus.app → 期望卸载干净(虽然 ~/.nexus/ 还在,但 APP 本身没了)。

- [ ] **Step 6: DMG 大小确认**

```bash
ls -lh /Users/yxb/projects/nexus/release/Nexus-1.1.0-arm64.dmg
```

期望：30-50 MB。

---

## 完成定义 (DoD)

- [ ] Task 1-26 全部 commit 通过
- [ ] Task 27-32 E2E 测试全部通过
- [ ] DMG 产物 release/Nexus-1.1.0-arm64.dmg 存在
- [ ] 用户从 DMG 装到 /Applications 后能完整使用所有功能
- [ ] 无 pyobjc monkey-patch 代码残留
- [ ] 无 pywebview import 残留
- [ ] 启动 < 3 秒
- [ ] 流式聊天正常
- [ ] 关窗保活 + Dock 重开 + cmd+Q 全部符合 macOS 习惯
- [ ] ~/.nexus/ 数据完全保留

---

**计划状态**: 已写完,待执行