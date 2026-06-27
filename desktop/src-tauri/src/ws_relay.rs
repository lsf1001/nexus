use std::collections::HashMap;

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::ipc::Channel;
use tokio::sync::RwLock;
use tokio_tungstenite::tungstenite::Message;

type WsTx = futures_util::stream::SplitSink<
    tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
    Message,
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
    pub rx_task: Option<tokio::task::JoinHandle<()>>,
}

#[tauri::command]
pub async fn ws_open(
    url: String,
    on_chunk: Channel<Value>,
    state: tauri::State<'_, RelayState>,
) -> Result<String, String> {
    let (ws, _) = tokio_tungstenite::connect_async(&url)
        .await
        .map_err(|e| format!("ws connect failed: {e}"))?;

    let session_id = uuid::Uuid::new_v4().to_string();
    let (tx, mut rx) = ws.split();

    let session_id_for_task = session_id.clone();
    let rx_task = tokio::spawn(async move {
        while let Some(msg) = rx.next().await {
            match msg {
                Ok(Message::Text(text)) => match serde_json::from_str::<Value>(&text) {
                    Ok(value) => {
                        if on_chunk.send(value).is_err() {
                            log::warn!("channel send failed, frontend disconnected");
                            break;
                        }
                    }
                    Err(e) => {
                        log::warn!("json parse failed: {e}, raw: {text}");
                    }
                },
                Ok(Message::Close(_)) => {
                    log::info!("ws closed by server: {session_id_for_task}");
                    break;
                }
                Ok(_) => {} // Ping/Pong/Frame 等忽略,避免把非业务帧转成 JSON。
                Err(e) => {
                    log::error!("ws error: {e}");
                    on_chunk
                        .send(serde_json::json!({
                            "type": "error",
                            "error_code": "ws_relay_error",
                            "content": e.to_string(),
                            "retryable": true
                        }))
                        .ok();
                    break;
                }
            }
        }
        log::info!("ws rx task ended: {session_id_for_task}");
    });

    state.sessions.write().await.insert(
        session_id.clone(),
        WsSession {
            tx,
            rx_task: Some(rx_task),
        },
    );

    log::info!("ws session opened: {session_id}");
    Ok(session_id)
}

#[tauri::command]
pub async fn ws_send(
    session_id: String,
    payload: Value,
    state: tauri::State<'_, RelayState>,
) -> Result<(), String> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_relay_state_new() {
        let state = RelayState::new();
        let sessions = state.sessions.read().await;
        assert!(sessions.is_empty());
    }
}
