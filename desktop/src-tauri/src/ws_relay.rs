use std::collections::HashMap;

use futures_util::{SinkExt, StreamExt};
use http::HeaderValue;
use serde_json::Value;
use tauri::ipc::Channel;
use tokio::sync::RwLock;
use tokio_tungstenite::tungstenite::{
    client::IntoClientRequest,
    Message,
};

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

/// Sec-WebSocket-Protocol 子协议前缀,见 `nexus.backend.api.ws.auth._WS_SUBPROTOCOL_PREFIX`。
///
/// WHY 固定前缀:`nexus-v1.token=<value>` 让 Rust relay 与浏览器原生
/// `new WebSocket(url, ['nexus-v1.token=...'])` 走同一协议解析路径,
/// 服务端优先读该 header(后端已实现),token 不再进 URL。
const WS_SUBPROTOCOL_PREFIX: &str = "nexus-v1.token=";

/// 把 tungstenite 错误映射成前端友好的分类。
///
/// 设计原则:
/// - 不返回 ``e.to_string()`` 原文 — tungstenite 错误通常带 URL / 协议细节,
///   暴露给前端 UI 等同向用户泄漏内部网络拓扑。
/// - 真错误已写 ``log::error!``,运维从 ``~/.nexus/logs/webview-error.log``
///   或控制台能拿到完整信息。
/// - 分类粒度按"用户能不能据此采取行动"划分,不是按错误类型穷举。
fn classify_ws_error(err: &tokio_tungstenite::tungstenite::Error) -> (&'static str, &'static str, bool) {
    use tokio_tungstenite::tungstenite::Error as E;
    match err {
        E::ConnectionClosed | E::AlreadyClosed => ("ws_closed", "连接已关闭", false),
        E::Io(_) => ("ws_io", "网络连接中断", true),
        E::Tls(_) => ("ws_tls", "TLS 握手失败", true),
        E::Http(_) => ("ws_http", "服务返回非 101 状态", true),
        E::Url(_) => ("ws_url", "WS URL 无效", false),
        E::Utf8 => ("ws_utf8", "WS 消息编码异常", false),
        E::Capacity(_) => ("ws_capacity", "WS 消息过大", false),
        E::Protocol(_) => ("ws_protocol", "WS 子协议协商失败", false),
        E::WriteBufferFull(_) => ("ws_buffer_full", "WS 发送缓冲已满", true),
        _ => ("ws_relay_error", "WS 内部错误", true),
    }
}

#[tauri::command]
pub async fn ws_open(
    url: String,
    token: String,
    on_chunk: Channel<Value>,
    state: tauri::State<'_, RelayState>,
) -> Result<String, String> {
    // token 必须非空;空 token 走 subprotocol 也会被服务端拒(空 expected 拒所有客户端),
    // 但 Rust 端这里提前失败可以省一次握手往返 + 让错误信息更直接。
    if token.is_empty() {
        return Err("ws token is empty;请在启动时注入 NEXUS_WS_TOKEN".to_string());
    }

    // 构造握手 Request,设 Sec-WebSocket-Protocol 子协议头。
    // token 不进 URL → 不进代理 access log / 错误堆栈 / 命令行 ps 输出。
    let mut request = (&url)
        .into_client_request()
        .map_err(|e| format!("ws build request failed: {e}"))?;
    let subproto_value = format!("{WS_SUBPROTOCOL_PREFIX}{token}");
    request.headers_mut().insert(
        "Sec-WebSocket-Protocol",
        HeaderValue::from_str(&subproto_value)
            .map_err(|e| format!("ws invalid subprotocol header: {e}"))?,
    );

    let (ws, _) = tokio_tungstenite::connect_async(request)
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
                    // 错误细节只写 log,不进 on_chunk — 前端 UI 用短文案,
                    // 避免 stack / URL / 系统路径等敏感信息泄漏到界面。
                    log::error!("ws error: {e}");
                    let (error_code, content, retryable) = classify_ws_error(&e);
                    on_chunk
                        .send(serde_json::json!({
                            "type": "error",
                            "error_code": error_code,
                            "content": content,
                            "retryable": retryable,
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

    #[test]
    fn test_ws_subprotocol_prefix_format() {
        // token 不应包含逗号 / 换行等 HTTP header-value 非法字符;
        // 真正的 token 来源是配置 / 环境变量,不在这里校验。约束:
        // 拼接后的 header value 必须是 ASCII 可见字符。
        let token = "abc123";
        let value = format!("{WS_SUBPROTOCOL_PREFIX}{token}");
        assert_eq!(value, "nexus-v1.token=abc123");
        assert!(HeaderValue::from_str(&value).is_ok());
    }

    #[test]
    fn test_ws_subprotocol_rejects_crlf() {
        // HeaderValue 不允许 CRLF → token 含 \r\n 时构造失败,返回明确错误
        // (而不是握手后服务端拒绝)。
        let bad_token = "abc\r\ninjected";
        let value = format!("{WS_SUBPROTOCOL_PREFIX}{bad_token}");
        assert!(HeaderValue::from_str(&value).is_err());
    }

    #[tokio::test]
    async fn test_relay_state_new() {
        let state = RelayState::new();
        let sessions = state.sessions.read().await;
        assert!(sessions.is_empty());
    }

    #[test]
    fn test_classify_ws_error_does_not_leak_details() {
        // 关键不变量:任何 error 都不会出现在 content 字段。
        // 调用方会把 content 直接展示给用户,泄漏 token / URL / 路径就完了。
        use tokio_tungstenite::tungstenite::Error;
        let cases: Vec<Error> = vec![
            Error::AlreadyClosed,
            Error::Utf8,
            // 模拟一个带 URL 的 Url 错误
            Error::Url(tokio_tungstenite::tungstenite::error::UrlError::UnsupportedUrlScheme),
        ];
        for err in &cases {
            let (code, content, _retryable) = classify_ws_error(err);
            assert!(!content.is_empty(), "分类文案不能为空:{code}");
            assert!(
                !content.contains("ws://"),
                "content 不能包含 ws URL:{content}"
            );
            assert!(
                !content.contains("wss://"),
                "content 不能包含 wss URL:{content}"
            );
            assert!(!content.contains('\n'), "content 不能多行:{content}");
        }
    }
}