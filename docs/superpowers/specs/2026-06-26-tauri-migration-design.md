# Nexus Tauri 迁移设计

**日期**: 2026-06-26
**作者**: Claude (via brainstorming)
**状态**: 已批准（用户 2026-06-26 确认）
**目标版本**: v1.1.0
**预计工期**: 4-5 天

---

## 1. 背景与动机

### 1.1 现状（pywebview + PyInstaller）

Nexus 桌面 APP 当前使用：

- **pywebview 6.2.1** 包装 macOS 系统 WKWebView
- **PyInstaller --osx-bundle-identifier** 生成 .app bundle
- 大量 **pyobjc monkey-patch** 实现 macOS 原生行为（关窗保活、Dock 重开、透明标题栏）

### 1.2 已解决的问题

- ✅ 启动器找不到 Python.framework（PyInstaller 6.20 + bundle identifier）
- ✅ 标题栏在 Dark Mode 下"黑色横条"
- ✅ 点击 X 直接退出
- ✅ Dock 点击不重开
- ✅ 两个 APP 同名冲突
- ✅ 闪白 + 多层结构（CSS 层面）

### 1.3 仍存在的问题

- ❌ **DMG 68 MB**（Python runtime 完整打包）
- ❌ **启动 2-3 秒**（Python 解释器 + 几百个包 import）
- ❌ **大量 monkey-patch**（pywebview 6.x `Event.set()` bug 强迫用反射）
- ❌ **PyInstaller 代码签名复杂**（sidecar 也要签）
- ❌ **后端升级要重打 DMG**（即使只是 Python 安全更新）

### 1.4 设计目标

迁移到 **Tauri 2 + Python sidecar**，获得：

- DMG 30-50 MB（去掉 pywebview + 部分 Python 打包优化）
- 启动 1-2 秒（无 pywebview 中间层）
- 配置代替 monkey-patch（macOS 行为全走 Tauri 内置 API）
- 后端独立可重打 sidecar（不重打桌面壳）
- 与 Hermes Agent 社区主流方案一致（参考 Hermes-CN-Desktop）

---

## 2. 关键决策

| 决策项          | 选择                            | 理由                                        |
| ------------ | ----------------------------- | ----------------------------------------- |
| Tauri 版本     | v2                            | 现代特性、Channel API、tray-icon 内置、社区主流        |
| WebSocket 流式 | Rust relay（tokio-tungstenite） | 生产验证、Hermes-CN-Desktop 同款、断线重连/心跳 Rust 处理 |
| Sidecar 打包   | PyInstaller onedir            | 跨平台成熟、DeepAgents/LangChain 兼容、风险最低        |
| 关窗行为         | 仅隐藏到 Dock（无托盘）                | macOS 原生习惯（Chrome/VS Code/Slack）          |
| 启动时机         | 异步起 sidecar + splash          | 避免 10-30s 卡顿、用户体验连贯                       |
| REST 调用      | 前端直连 FastAPI                  | 改动最小、调试方便、Rust 代码量少                       |

---

## 3. 架构

### 3.1 总览

```
┌─────────────────────────────────────────────────────┐
│ Nexus.app (DMG ~50MB)                               │
│                                                     │
│  ┌─ Tauri 主进程 (Rust, ~10MB) ──────────────────┐ │
│  │  • 启动 WKWebView 窗口                        │ │
│  │  • 关窗保活 + Dock 重开 (Tauri 内置 API)       │ │
│  │  • 透明 titlebar (tauri.conf.json 一行)        │ │
│  │  • 异步 spawn nexus-runtime sidecar           │ │
│  │  • WebSocket relay (tokio-tungstenite)        │ │
│  │  • 进程崩溃自动重启 (supervisor)               │ │
│  └──────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ nexus-runtime/ (PyInstaller onedir, ~40MB) ───┐│
│  │  • FastAPI + Uvicorn (port 30000)              ││
│  │  • DeepAgents + MemoryMiddleware               ││
│  │  • QualityGateMiddleware + MCP                 ││
│  │  • SQLite (sessions/messages/memory_legacy)    ││
│  └──────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ frontend/dist/ (~2MB) ────────────────────────┐│
│  │  • React 19 + Vite (现有代码不动)              ││
│  │  • useWebSocket → useTauriWs (hook 改造)       ││
│  │  • 新增 SplashView (splash 页)                 ││
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
        ↓                       ↓
   HTTP/WS 直连            HTTP/WS 通过
   (REST API)              Rust relay (流式)
```

### 3.2 与现状的关键差异

| 维度            | 现状                                                        | 迁移后                                                 |
| ------------- | --------------------------------------------------------- | --------------------------------------------------- |
| 窗口管理          | pywebview + pyobjc patch                                  | Tauri 内置 + `tauri.conf.json`                        |
| 关窗保活          | monkey-patch `WindowDelegate.windowShouldClose_`          | `on_window_event(CloseRequested) + prevent_close()` |
| Dock 重开       | monkey-patch `AppDelegate.applicationShouldHandleReopen_` | `RunEvent::Reopen`                                  |
| 透明标题栏         | pyobjc `NSWindow.setTitlebarAppearsTransparent_`          | `titleBarStyle: "Transparent"`                      |
| 强制 Light Mode | `NSApp.setAppearance_(aqua)`                              | 移除（用 system default + CSS）                          |
| WebView       | WKWebView（pywebview）                                      | WKWebView（Tauri）**同一个 webview**                     |
| WebSocket 流式  | pywebview 直连                                              | Rust relay + Tauri Channel                          |
| Sidecar 打包    | PyInstaller --onedir (含 webview)                          | PyInstaller --onedir (无 webview)                    |
| 启动序列          | 同步等 sidecar 起来                                            | 异步起 + splash                                        |

---

## 4. 目录结构

```
nexus/
├── nexus/backend/                    # Python 后端(业务代码不动)
│   ├── main.py                       # FastAPI app(不变)
│   ├── runtime_main.py               # NEW: sidecar 入口(简化的 main.py,无 webview)
│   ├── db.py                         # SQLite + 自动迁移(不变)
│   ├── agent.py                      # DeepAgents 封装(不变)
│   └── ...
├── nexus/backend/launcher.py         # 保留:dev 模式启动器(webview + uvicorn)
├── frontend/                         # React 前端
│   ├── src/
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts       # 现有(保留)
│   │   │   └── useTauriWs.ts         # NEW: Tauri Channel 版
│   │   ├── components/desktop/
│   │   │   └── SplashView.tsx        # NEW: 启动 splash
│   │   └── App.tsx                   # 加 status 判断渲染 Splash 或主页
│   └── ...
├── desktop/                          # NEW: Tauri 项目根
│   ├── src-tauri/                    # Rust
│   │   ├── Cargo.toml                # 依赖: tauri 2 + tokio + tokio-tungstenite + reqwest
│   │   ├── tauri.conf.json           # 窗口/CSP/bundle/icon
│   │   ├── build.rs                  # tauri_build::build()
│   │   ├── icons/
│   │   │   ├── 32x32.png
│   │   │   ├── 128x128.png
│   │   │   ├── 128x128@2x.png
│   │   │   ├── icon.icns             # 复用 scripts/nexus.icns
│   │   │   └── icon.ico              # Windows (未来)
│   │   ├── binaries/                 # sidecar 暂存(打包后塞进 .app)
│   │   └── src/
│   │       ├── main.rs               # 入口、窗口事件、sidecar spawn
│   │       ├── runtime.rs            # sidecar 管理 + 健康检查 + supervisor
│   │       └── ws_relay.rs           # WebSocket relay + Tauri Channel
│   ├── src/                          # (可选)前端 Tauri 桥代码,如不需要可空
│   ├── package.json                  # tauri dev / build 脚本
│   └── .gitignore
├── scripts/
│   ├── build_dmg.sh                  # 重写: tauri build + DMG
│   └── build_sidecar.sh              # NEW: PyInstaller onedir
└── docs/superpowers/specs/
    └── 2026-06-26-tauri-migration-design.md
```

---

## 5. 关键模块设计

### 5.1 Tauri 配置 (`desktop/src-tauri/tauri.conf.json`)

```json
{
  "$schema": "https://schema.tauri.app/config/2.0.0",
  "productName": "Nexus",
  "version": "1.1.0",
  "identifier": "cn.yexiaobai.nexus",
  "build": {
    "beforeDevCommand": "cd ../frontend && npm run dev",
    "beforeBuildCommand": "cd ../frontend && npm run build",
    "devUrl": "http://localhost:30077",
    "frontendDist": "../frontend/dist"
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
        "hiddenTitle": true
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

### 5.2 Rust 主进程 (`desktop/src-tauri/src/main.rs`)

```rust
use tauri::{Manager, RunEvent, WindowEvent};

mod runtime;
mod ws_relay;

#[tokio::main]
async fn main() {
    env_logger::init();

    let app_state = runtime::AppState::new();

    tauri::Builder::default()
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
                    log::error!("sidecar failed: {e}");
                    handle.emit("runtime-status", RuntimeStatus::Failed(e.to_string())).ok();
                    return;
                }
                runtime::supervise_sidecar(&handle).await;
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            // 关窗 → 隐藏到 Dock(不退出)
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

            // 用户 Quit (cmd+Q) → 关闭 sidecar
            if let RunEvent::ExitRequested { .. } = event {
                runtime::shutdown_sidecar(app_handle);
            }
        });
}
```

### 5.3 Sidecar 管理 (`desktop/src-tauri/src/runtime.rs`)

```rust
use std::sync::Arc;
use tokio::sync::RwLock;
use tokio::process::{Command, Child};
use tauri::{AppHandle, Manager, Emitter};

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

pub async fn start_sidecar(app: &AppHandle) -> Result<(), String> {
    let state: tauri::State<AppState> = app.state();

    // Tauri 解析 externalBin 路径(开发模式: src-tauri/binaries/,打包后: Contents/MacOS/)
    let sidecar_path = app
        .path()
        .resolve("nexus-runtime", tauri::path::BaseDirectory::Resource)
        .map_err(|e| e.to_string())?;

    let mut cmd = Command::new(sidecar_path);
    cmd.args(["--host", "127.0.0.1", "--port", "30000"]);

    let child = cmd.spawn().map_err(|e| format!("spawn failed: {e}"))?;

    *state.sidecar.write().await = Some(child);

    // 健康检查:轮询 /health 直到 200 或超时 30s
    wait_for_health(&state.api_base, 30).await?;

    app.emit("runtime-status", RuntimeStatus::Ready).ok();
    Ok(())
}

async fn wait_for_health(url: &str, timeout_secs: u64) -> Result<(), String> {
    let deadline = tokio::time::Duration::from_secs(timeout_secs);
    let start = tokio::time::Instant::now();
    while start.elapsed() < deadline {
        if reqwest::get(format!("{url}/health")).await.is_ok() {
            return Ok(());
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
    }
    Err("sidecar health check timeout".into())
}

pub async fn supervise_sidecar(app: &AppHandle) {
    // 监控 sidecar,崩溃则自动重启(最多 3 次)
    let mut retries = 0;
    while retries < 3 {
        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
        let state: tauri::State<AppState> = app.state();
        let mut guard = state.sidecar.write().await;
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(Some(status)) if !status.success() => {
                    log::warn!("sidecar crashed: {status}");
                    retries += 1;
                    if let Err(e) = start_sidecar(app).await {
                        log::error!("restart failed: {e}");
                        return;
                    }
                }
                _ => {}
            }
        }
    }
}

pub fn shutdown_sidecar(app: &AppHandle) {
    let state: tauri::State<AppState> = app.state();
    if let Ok(mut guard) = state.sidecar.try_write() {
        if let Some(mut child) = guard.take() {
            child.kill().ok();
        }
    }
}

#[derive(serde::Serialize, Clone)]
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
```

### 5.4 WebSocket Relay (`desktop/src-tauri/src/ws_relay.rs`)

设计要点：

- `RelayState` 持有 `HashMap<session_id, WsSession>`（用 `RwLock` 保护）
- 每个 `WsSession` 持有 `SplitSink`（发）和 `JoinHandle<rx_task>`（收）
- `Channel<T>` 是 Tauri 2 IPC 流式原语：前端创建 `new Channel<T>()` 传给 invoke，Rust 端 `channel.send(value)` emit 给前端
- `Channel::clone()` 可在 spawned task 里持有副本，独立于原调用栈

```rust
use std::collections::HashMap;
use tokio::sync::RwLock;
use futures_util::{SinkExt, StreamExt};
use tauri::Channel;
use tokio_tungstenite::tungstenite::Message;

type WsTx = futures_util::stream::SplitSink<
    tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>
    >,
    Message,
>;

pub struct RelayState {
    pub sessions: RwLock<HashMap<String, WsSession>>,
}

pub struct WsSession {
    pub tx: WsTx,
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
    let (tx, _rx) = ws.split();

    state.sessions.write().await.insert(
        session_id.clone(),
        WsSession { tx, rx_task: None },
    );

    Ok(session_id)
}

#[tauri::command]
pub async fn ws_send(
    session_id: String,
    payload: serde_json::Value,
    on_chunk: Channel<serde_json::Value>,
    state: tauri::State<'_, RelayState>,
) -> Result<(), String> {
    // 1. 取出 session,启动接收 task(用 Channel.clone() 在 task 里发)
    {
        let mut sessions = state.sessions.write().await;
        let session = sessions.get_mut(&session_id).ok_or("session not found")?;

        let on_chunk_clone = on_chunk.clone();
        let session_id_for_task = session_id.clone();
        session.rx_task = Some(tokio::spawn(async move {
            // 此处需重构:rx 当前属于 ws_open 时拆出的 _rx,需放进 WsSession
            // 实施阶段会把 WsSession 拆出 rx 字段,由 task 持有
            let mut rx = /* TODO(plan): 接入 WsSession.rx */
            while let Some(msg) = rx.next().await {
                if let Ok(Message::Text(text)) = msg {
                    if let Ok(value) = serde_json::from_str(&text) {
                        if on_chunk_clone.send(value).is_err() { break; }
                    }
                }
            }
            log::info!("ws session {session_id_for_task} rx task ended");
        }));
    }

    // 2. 发送 payload
    let mut sessions = state.sessions.write().await;
    let session = sessions.get_mut(&session_id).ok_or("session gone")?;
    session.tx
        .send(Message::Text(payload.to_string()))
        .await
        .map_err(|e| format!("ws send failed: {e}"))?;

    Ok(())
}

#[tauri::command]
pub async fn ws_close(
    session_id: String,
    state: tauri::State<'_, RelayState>,
) -> Result<(), String> {
    let mut sessions = state.sessions.write().await;
    if let Some(mut session) = sessions.remove(&session_id) {
        if let Some(task) = session.rx_task.take() { task.abort(); }
        session.tx.close().await.ok();
    }
    Ok(())
}
```

**实施阶段需细化**：把 `SplitStream` (rx) 也存进 `WsSession`，由 rx_task 通过 `Arc<Mutex<...>>` 持有，避免当前简化的 `_rx` 丢失问题。

### 5.5 Sidecar 入口 (`nexus/backend/runtime_main.py`)

```python
"""Sidecar 入口: 只跑 FastAPI/uvicorn,不开 webview。

打包时被 PyInstaller 打成 nexus-runtime 二进制(无 webview 依赖)。
Tauri 主进程 spawn 这个 sidecar,绑定 127.0.0.1:30000。
"""

import argparse
import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    args = parser.parse_args()

    # PyInstaller 打包后,前端 dist 在 .app/Contents/Resources/frontend/
    import os
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        bundled_frontend = Path(sys._MEIPASS) / "frontend"
        if not bundled_frontend.exists():
            bundled_frontend = Path(sys._MEIPASS).parent / "Resources" / "frontend"
        if bundled_frontend.exists():
            os.environ["NEXUS_FRONTEND_DIST"] = str(bundled_frontend)

    from nexus.backend.main import app
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 5.6 前端 Tauri WebSocket Hook (`frontend/src/hooks/useTauriWs.ts`)

```typescript
import { invoke, Channel } from '@tauri-apps/api/core';
import { useEffect, useRef, useState } from 'react';

// 与现有 useWebSocket.ts 的 StreamMsg 类型保持一致(WS 协议不变)
export interface StreamMsg {
  type: 'thinking' | 'chunk' | 'final' | 'done' | 'error';
  data?: unknown;
}

interface UseTauriWsResult {
  connected: boolean;
  send: (payload: unknown) => Promise<void>;
}

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
        const sessionId = await invoke<string>('ws_open', { url });
        if (cancelled) return;
        sessionRef.current = sessionId;
        setConnected(true);
      } catch (e) {
        onMessage({ type: 'error', data: String(e) });
      }
    })();

    return () => {
      cancelled = true;
      if (sessionRef.current) {
        invoke('ws_close', { sessionId: sessionRef.current }).catch(() => {});
      }
    };
  }, [url]);

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

### 5.7 Splash 视图 (`frontend/src/components/desktop/SplashView.tsx`)

```tsx
import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';

interface RuntimeStatus {
  type: 'Starting' | 'Ready' | 'Failed';
  data?: string;
}

export function SplashView() {
  const [status, setStatus] = useState<RuntimeStatus>({ type: 'Starting' });

  useEffect(() => {
    const unlisten = listen<RuntimeStatus>('runtime-status', (e) => {
      setStatus(e.payload);
    });
    return () => { unlisten.then((fn) => fn()); };
  }, []);

  if (status.type === 'Failed') {
    return (
      <div className="splash-error">
        <h2>后端启动失败</h2>
        <p>{status.data}</p>
        <button onClick={() => location.reload()}>重试</button>
      </div>
    );
  }

  return (
    <div className="splash">
      <div className="splash-logo">N</div>
      <p>正在启动 Nexus...</p>
    </div>
  );
}
```

---

## 6. 数据流：流式聊天

```
前端 React               Rust WS relay              FastAPI/DeepAgents
   │                         │                            │
   │  invoke('ws_open')      │                            │
   ├────────────────────────►│                            │
   │                         │  tokio-tungstenite connect │
   │                         ├───────────────────────────►│
   │  return session_id      │  ws://127.0.0.1:30000/...  │
   │◄────────────────────────┤                            │
   │                         │                            │
   │  invoke('ws_send', {    │                            │
   │    sessionId, payload,  │                            │
   │    onChunk: Channel    │                            │
   │  })                     │                            │
   ├────────────────────────►│                            │
   │                         │  send(payload)             │
   │                         ├───────────────────────────►│
   │                         │                            │
   │                         │  on_message('thinking')    │
   │                         │◄───────────────────────────┤
   │  Channel.send(thinking) │                            │
   │◄────────────────────────┤                            │
   │                         │  on_message('chunk')       │
   │                         │◄───────────────────────────┤
   │  Channel.send(chunk)    │                            │
   │◄────────────────────────┤  ... (N chunks) ...        │
   │                         │                            │
   │                         │  on_message('final')       │
   │                         │◄───────────────────────────┤
   │  Channel.send(final)    │                            │
   │◄────────────────────────┤                            │
   │                         │  on_message('done')        │
   │                         │◄───────────────────────────┤
   │  Channel.send(done)     │                            │
   │◄────────────────────────┤                            │
   │                         │  ws close                  │
   │                         ├───────────────────────────►│
```

---

## 7. 错误处理

| 场景                      | 处理                                                                 |
| ----------------------- | ------------------------------------------------------------------ |
| Sidecar 启动失败（Python 崩溃） | supervisor 检测，3 次重试；失败后 `runtime-status: Failed` 事件，前端 splash 切错误页 |
| Sidecar 健康检查超时（30s）     | 弹超时页，给"重试"按钮                                                       |
| WebSocket relay 中断      | Channel 收到 `{type: 'error'}` 事件，前端显示重连按钮                           |
| WebView 加载失败            | splash 监听 `tauri://error`，fallback 到错误页                            |
| Python 进程被用户 kill       | Tauri 主进程检测到 sidecar 退出，supervisor 尝试重启                            |
| 用户主动 Quit (cmd+Q)       | Tauri `RunEvent::ExitRequested` → shutdown sidecar → 正常退出          |

---

## 8. 测试策略

| 层级         | 测试                                                   | 工具                              |
| ---------- | ---------------------------------------------------- | ------------------------------- |
| Rust 单元测试  | ws_relay 转发逻辑、runtime 进程管理                           | `cargo test`                    |
| Rust 集成测试  | sidecar spawn + health check + 重启                    | `cargo test --test integration` |
| 前端 hook 测试 | useTauriWs mock Channel                              | Vitest                          |
| 端到端        | `pnpm tauri:dev` 启动后手动验证                             | 手动                              |
| 打包验证       | `bash scripts/build_dmg.sh` → 装到 /Applications → 跑全套 | 手动 + CI                         |

**CI 新增 job：**

- `rust-test`: `cargo test --all-features`
- `web-test`: 现有 Vitest
- `release-desktop`: `tauri build` 跑通（无需签名）

---

## 9. 迁移步骤

| 阶段                                                | 工作量       | 验证              |
| ------------------------------------------------- | --------- | --------------- |
| 1. 拆分 launcher.py → runtime_main.py（去 webview 部分） | 0.5 天     | dev 模式跑得通       |
| 2. 创建 desktop/ + Cargo.toml + tauri.conf.json     | 0.5 天     | `cargo check` 过 |
| 3. main.rs：窗口 + 关窗/Dock 重开 + sidecar spawn        | 1 天       | `cargo run` 出窗口 |
| 4. ws_relay.rs + 前端 useTauriWs hook               | 1 天       | 流式响应正常          |
| 5. build_sidecar.sh + build_dmg.sh 串联             | 0.5 天     | DMG 产出          |
| 6. .app bundle 装到 /Applications 测试                | 0.5 天     | 完整流程通过          |
| **合计**                                            | **4-5 天** |                 |

---

## 10. 兼容性

### 10.1 保留

- `nexus/backend/launcher.py`（dev 模式启动器，本地开发用 `python -m nexus.backend.launcher`）
- `nexus/backend/main.py`（FastAPI app，零改动）
- `frontend/`（React 业务代码，仅 `useWebSocket` hook 调用方需小改）
- `scripts/nexus.icns`（图标资源）
- `~/.nexus/`（运行时数据目录，所有 SQLite / AGENTS.md 都在这里）

### 10.2 弃用

- pywebview 依赖（`pyproject.toml` 中移除）
- 现有的 `Event.set()` monkey-patch
- 现有的 `WindowDelegate` / `AppDelegate` monkey-patch
- 现有的 `NSApp.setAppearance_(aqua)` 强制 Light Mode

### 10.3 不破坏

- 现有用户的 `~/.nexus/nexus.db`、`AGENTS.md`、`models.json` 完全兼容
- WebSocket 协议格式不变（前端接收的 StreamMsg 形状一致）
- REST API 路径不变（前端 fetch 直连 127.0.0.1:30000）

---

## 11. 风险与缓解

| 风险                                       | 概率  | 影响  | 缓解                                               |
| ---------------------------------------- | --- | --- | ------------------------------------------------ |
| macOS 10.15 (Catalina) 上 Tauri 2 要求的 WKWebView 版本不足 | 低   | 中   | 已在 `minimumSystemVersion: "10.15"` 声明；如用户 < 10.15 给清晰错误提示 |
| PyInstaller onedir 打包后路径解析错              | 中   | 高   | 复用现有 `sys._MEIPASS` 模式，runtime_main.py 验证过       |
| tokio-tungstenite 长连接断线                  | 中   | 中   | Rust 端实现心跳 + 自动重连，前端 Channel 收到 `error` 事件时显示重连  |
| Tauri Channel 在高频 chunk 下丢消息             | 低   | 高   | 单次 WS session 限 1 个 Channel 实例；如不够后续可批量发送        |
| 进程 supervisor 误判（child.try_wait 返回 None） | 低   | 低   | 加日志，必要时引入专用健康检查任务                                |
| 启动 splash 阶段 React 渲染报错                  | 低   | 中   | splash 是独立组件，错误降级到错误页                            |
| DMG 50MB 比预期大                            | 中   | 低   | 用 `cargo` LTO + `strip`（已在 Hermes-CN-Desktop 验证） |

---

## 12. 不在范围内

- macOS 代码签名 / 公证（用户明确不需要）
- 自动更新（`tauri-plugin-updater`）
- 系统托盘图标（用户选择不要）
- 多窗口支持
- Windows / Linux 打包（仅 macOS arm64 + x86_64）
- CLI 子命令（保持 launcher.py 的 argparse 形式，作为 dev 模式入口）

---

## 13. 参考资料

- Hermes-CN-Desktop: https://github.com/Eynzof/Hermes-CN-Desktop
  - Tauri 2 + Rust 25% + TypeScript 61.7% 参考实现
  - 关键模式：sidecar spawn、WS relay、tray-icon、supervisor
- Tauri 2 官方文档: https://v2.tauri.app/
- tokio-tungstenite: https://docs.rs/tokio-tungstenite/

---

**Spec 状态**: 已批准，待写实施计划