// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod runtime;
mod ws_relay;

use tauri::{Emitter, Manager, RunEvent, WindowEvent};

fn main() {
    env_logger::init();

    let app_state = runtime::AppState::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .manage(app_state)
        .manage(ws_relay::RelayState::new())
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
                    handle
                        .emit("runtime-status", runtime::RuntimeStatus::Failed(e))
                        .ok();
                    return;
                }
                runtime::supervise_sidecar(handle).await;
            });
            Ok(())
        })
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
                log::info!("ExitRequested — shutdown sidecar");
                runtime::shutdown_sidecar(app_handle);
            }
        });
}