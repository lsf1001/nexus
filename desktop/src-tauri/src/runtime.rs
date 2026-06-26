use std::sync::Arc;
use std::time::Duration;

use once_cell::sync::Lazy;
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tokio::process::{Child, Command};
use tokio::sync::RwLock;
use tokio::time::Instant;

/// 全局 sidecar PID:主进程任何路径退出(cmd+Q / SIGTERM / panic)都靠这个杀子进程
/// 不依赖 Tauri RunEvent,因为 macOS terminateApp 直接 SIGTERM 主进程,不走 ExitRequested
static SIDECAR_PID: Lazy<std::sync::Mutex<Option<u32>>> =
    Lazy::new(|| std::sync::Mutex::new(None));

/// atexit 钩子:主进程退出前同步杀 sidecar
fn kill_sidecar_at_exit() {
    if let Ok(mut guard) = SIDECAR_PID.lock() {
        if let Some(pid) = guard.take() {
            unsafe {
                libc::kill(pid as i32, libc::SIGKILL);
            }
            eprintln!("[nexus] atexit: SIGKILL sidecar pid={pid}");
        }
    }
}

pub fn set_sidecar_pid(pid: u32) {
    *SIDECAR_PID.lock().unwrap() = Some(pid);
}

pub struct AppState {
    pub sidecar: Arc<RwLock<Option<Child>>>,
    #[allow(dead_code)]
    pub api_base: String,
    #[allow(dead_code)]
    pub ws_url: String,
}

impl AppState {
    pub fn new() -> Self {
        // 安装 atexit 兜底,主进程任何路径退出都先杀 sidecar
        static INIT: std::sync::Once = std::sync::Once::new();
        INIT.call_once(|| {
            // libc::atexit 需 unsafe extern "C" fn
            extern "C" fn atexit_handler() {
                kill_sidecar_at_exit();
            }
            unsafe {
                libc::atexit(atexit_handler);
            }
        });
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

    // 把 PID 写到全局,atexit 兜底
    if let Some(pid) = child.id() {
        set_sidecar_pid(pid);
    }

    *state.sidecar.write().await = Some(child);

    wait_for_health(&state.api_base, 30).await?;
    log::info!("sidecar ready");

    app.emit("runtime-status", RuntimeStatus::Ready).ok();
    Ok(())
}

fn resolve_sidecar_path(_app: &AppHandle) -> Result<std::path::PathBuf, String> {
    use tauri::path::BaseDirectory;

    // 1. 打包模式:用 current_exe() 反推 .app 内的 Resources 目录
    //    tauri 把 release/nexus-runtime/ 放在 Resources/_up_/_up_/release/nexus-runtime/
    if let Ok(exe) = std::env::current_exe() {
        // exe = .../Nexus.app/Contents/MacOS/nexus-desktop
        // resources = .../Nexus.app/Contents/Resources
        if let Some(resources) = exe.parent().and_then(|p| p.parent()).map(|p| p.join("Resources")) {
            // Tauri 2 资源路径会带 _up_/_up_ 反映 ../../ 跳出
            for rel in [
                "_up_/_up_/release/nexus-runtime/nexus-runtime",
                "release/nexus-runtime/nexus-runtime",
                "nexus-runtime/nexus-runtime",
                "nexus-runtime",
            ] {
                let p = resources.join(rel);
                if p.exists() {
                    return Ok(p);
                }
            }
        }
    }

    // 2. 兜底:Tauri 提供的 resource 解析
    if let Ok(p) = _app.path().resolve("nexus-runtime/nexus-runtime", BaseDirectory::Resource) {
        if p.exists() {
            return Ok(p);
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
        "sidecar binary not found. tried: bundle Resources, dev bundle: {dev_bundle:?}, dev single: {dev_path:?}"
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
    eprintln!("[nexus] shutdown_sidecar called");
    let state: tauri::State<AppState> = app.state();
    let child_opt = {
        let Ok(mut guard) = state.sidecar.try_write() else {
            eprintln!("[nexus] shutdown_sidecar: try_write failed");
            return;
        };
        guard.take()
    };
    let Some(mut child) = child_opt else {
        eprintln!("[nexus] shutdown_sidecar: no child to kill");
        return;
    };
    eprintln!("[nexus] killing sidecar");
    if let Some(pid) = child.id() {
        unsafe {
            libc::kill(pid as i32, libc::SIGKILL);
        }
        eprintln!("[nexus] sent SIGKILL to sidecar pid={pid}");
    } else {
        eprintln!("[nexus] child.id() returned None");
    }
    drop(child);
}