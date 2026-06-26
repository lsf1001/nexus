use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tokio::process::{Child, Command};
use tokio::sync::RwLock;
use tokio::time::Instant;

pub struct AppState {
    pub sidecar: Arc<RwLock<Option<Child>>>,
    #[allow(dead_code)]
    pub api_base: String,
    #[allow(dead_code)]
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
pub async fn get_runtime_status(state: tauri::State<'_, AppState>) -> Result<RuntimeStatus, String> {
    if state.sidecar.read().await.is_some() {
        Ok(RuntimeStatus::Ready)
    } else {
        Ok(RuntimeStatus::Starting)
    }
}

/// 异步启动 sidecar 并等健康检查通过。
/// 启动后 emit "runtime-status: Ready" 给前端。
pub async fn start_sidecar(app: &AppHandle) -> Result<(), String> {
    let state: tauri::State<AppState> = app.state();

    let sidecar_path = resolve_sidecar_path(app)?;
    log::info!("starting sidecar: {sidecar_path:?}");

    let mut cmd = Command::new(&sidecar_path);
    cmd.args(["--host", "127.0.0.1", "--port", "30000"])
        .kill_on_drop(true);

    let child = cmd
        .spawn()
        .map_err(|e| format!("spawn failed: {e} (path: {sidecar_path:?})"))?;

    *state.sidecar.write().await = Some(child);

    wait_for_health(&state.api_base, 30).await?;
    log::info!("sidecar ready");

    app.emit("runtime-status", RuntimeStatus::Ready).ok();
    Ok(())
}

fn resolve_sidecar_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    use tauri::path::BaseDirectory;

    // 1. 打包模式:Resource 目录(整个 onedir 目录被 externalBin 复制到 .app/Contents/Resources/)
    if let Ok(p) = app.path().resolve("nexus-runtime/nexus-runtime", BaseDirectory::Resource) {
        if p.exists() {
            return Ok(p);
        }
    }

    // 2. 再尝试 .app/Contents/MacOS/(Tauri 2 习惯)
    if let Ok(resource) = app.path().resource_dir() {
        let macos_path = resource
            .parent()
            .unwrap_or(&resource)
            .join("MacOS")
            .join("nexus-runtime");
        if macos_path.exists() {
            return Ok(macos_path);
        }
    }

    // 3. dev 模式:用 onedir 完整 bundle(release/nexus-runtime/nexus-runtime)
    //    PyInstaller onedir 需要 _internal/ 目录里的 Python stdlib
    let dev_bundle = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("release")
        .join("nexus-runtime")
        .join("nexus-runtime");
    if dev_bundle.exists() {
        return Ok(dev_bundle);
    }

    // 4. 兜底:src-tauri/binaries/nexus-runtime-{arch}-{platform}(单文件,可能缺 _internal)
    let dev_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("binaries")
        .join(format!("nexus-runtime-{}", std::env::consts::ARCH));
    if dev_path.exists() {
        return Ok(dev_path);
    }

    Err(format!(
        "sidecar binary not found. tried: resource dir, .app/Contents/MacOS/, dev bundle: {dev_bundle:?}, dev single: {dev_path:?}"
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
                            app.emit("runtime-status", RuntimeStatus::Failed(e)).ok();
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
    let child_opt = {
        let Ok(mut guard) = state.sidecar.try_write() else {
            return;
        };
        guard.take()
    };
    if let Some(mut child) = child_opt {
        log::info!("killing sidecar");
        tokio::spawn(async move {
            if let Err(e) = child.kill().await {
                log::error!("kill sidecar failed: {e}");
            }
        });
    }
}