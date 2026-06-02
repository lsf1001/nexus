import asyncio
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .agent import create_agent
from .config import CONFIG
from .mcp import load_all_mcp_tools
from .models_config import get_active_model
from .routes import model_config as model_config_routes
from .sessions import router as sessions_router

_agent = None
_mcp_tools: list[Any] = []
_agent_lock = threading.RLock()
_ws_clients: list[WebSocket] = []
_clients_lock = threading.RLock()

# 微信消息处理线程池（全局复用）
_wechat_executor: ThreadPoolExecutor | None = None
_main_loop: asyncio.AbstractEventLoop | None = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _handle_wechat_message(channel_message) -> None:
    """处理微信消息，转发到所有 WebSocket 客户端并生成回复"""
    try:
        from .channels.base import ChannelMessage

        if not isinstance(channel_message, ChannelMessage):
            logger.error(f"Invalid message type: {type(channel_message)}")
            return

        logger.info(
            f"_handle_wechat_message CALLED: user={channel_message.user_id}, content={channel_message.content[:50]}..."
        )

        message_data = {
            "type": "wechat_message",
            "content": channel_message.content,
            "channel_id": channel_message.channel_id,
            "user_id": channel_message.user_id,
            "session_id": channel_message.session_id,
        }

        with _clients_lock:
            clients = list(_ws_clients)

        logger.info(f"WebSocket clients: {len(clients)}")

        for client in clients:
            try:
                if _main_loop and not _main_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(client.send_json(message_data), _main_loop)
                else:
                    logger.warning("主事件循环不可用，跳过 WebSocket 广播")
            except Exception as e:
                logger.warning(f"广播失败: {e}")

        # 在线程池中执行异步处理
        global _wechat_executor
        if _wechat_executor is None:
            _wechat_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wechat-")
        _wechat_executor.submit(_process_wechat_message_sync, channel_message)
    except Exception as e:
        logger.error(f"Error in _handle_wechat_message: {e}")


# 微信用户 session 映射
_wechat_sessions: dict[str, str] = {}  # user_id -> session_id


def _process_wechat_message_sync(channel_message) -> None:
    """在线程池中调用异步处理函数：将协程提交到主事件循环执行。

    这样 DeepAgents 内部的连接池、句柄都能复用主循环资源，
    而非每次创建销毁临时循环。
    """
    if _main_loop is None or _main_loop.is_closed():
        logger.error("主事件循环不可用，跳过微信消息处理")
        return
    try:
        future = asyncio.run_coroutine_threadsafe(_process_wechat_message(channel_message), _main_loop)
        future.result(timeout=300)
    except Exception as e:
        logger.error(f"处理微信消息失败: {e}")


async def _process_wechat_message(channel_message) -> None:
    """处理微信消息：调用 Agent 生成回复并通过微信通道发送"""
    try:
        logger.info(f"Processing WeChat message: {channel_message.content[:50]}...")

        with _agent_lock:
            agent = _agent
        if not agent:
            logger.error("No agent available for WeChat message")
            return

        from .channels.wechat import _send_message, get_active_wechat_channel

        channel = get_active_wechat_channel()
        logger.info(f"Active channel: {channel}, account: {channel._account if channel else None}")
        if not channel or not channel._account:
            logger.error("No active WeChat channel")
            return

        # 获取或创建会话
        user_id = channel_message.user_id
        account_id = channel._account.account_id if channel._account else "unknown"

        # 检查是否需要创建新会话（会话不存在于数据库时）
        should_create = user_id not in _wechat_sessions
        if not should_create:
            existing_session_id = _wechat_sessions[user_id]
            from .db import get_session

            existing_session = get_session(existing_session_id)
            if not existing_session:
                should_create = True

        if should_create:
            # 创建新会话
            from .db import create_session

            session_id = str(uuid.uuid4())
            # 提取微信用户ID的简短标识
            wx_id = channel_message.user_id.split("@")[0][:8]
            acc_id = account_id[:8]
            title = f"微信 {acc_id} {wx_id}"
            create_session(session_id, title=title, channel="wechat")
            _wechat_sessions[user_id] = session_id
            logger.info(f"Created session for WeChat user {user_id}: {session_id}")
        else:
            session_id = _wechat_sessions[user_id]

        # 保存用户消息
        from .db import add_message

        add_message(str(uuid.uuid4()), session_id, "user", channel_message.content)

        # 发送正在输入状态
        try:
            from .channels.wechat import _send_typing

            await _send_typing(
                channel.base_url,
                channel._account.token,
                channel_message.user_id,
                context_token=channel_message.reply_to,
            )
        except Exception as e:
            logger.debug(f"Failed to send typing indicator: {e}")

        # 使用 SessionManager 构建带记忆的 prompt
        from .sessions import get_session_manager

        session_manager = get_session_manager()
        prompt = session_manager.build_prompt(session_id, channel_message.content)

        # 调用 Agent
        full_response = ""
        async for chunk in agent.astream({"messages": prompt["messages"]}, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            if "model" in chunk:
                model_data = chunk.get("model", {})
                if model_data and isinstance(model_data, dict):
                    msgs = model_data.get("messages", [])
                    for msg in msgs:
                        content = getattr(msg, "content", "") or ""
                        if content:
                            full_response += content

        if full_response:
            # 去除思考标签后发送
            normalized = full_response.replace("<think>", "").replace("</think>", "").strip()

            # 保存助手回复（包含思考过程）
            add_message(str(uuid.uuid4()), session_id, "assistant", full_response)

            # 发送回复到微信（不含思考标签）
            context_token = channel_message.reply_to
            await _send_message(
                channel.base_url,
                channel._account.token,
                channel_message.user_id,
                normalized,
                context_token,
            )
            logger.info(f"WeChat response sent to {channel_message.user_id}")
    except Exception as e:
        logger.error(f"Error processing WeChat message: {e}")


def _get_frontend_path() -> Path | None:
    """获取前端构建目录路径。"""
    # 安装目录下的 frontend
    nexus_home = Path.home() / ".nexus"
    frontend_path = nexus_home / "frontend" / "dist"
    if frontend_path.exists():
        return nexus_home / "frontend" / "dist"

    # 开发模式：项目目录下的 frontend
    project_frontend = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if project_frontend.exists():
        return project_frontend

    return None


def _create_agent_with_model(model_config: dict | None = None, mcp_tools: list[Any] | None = None):
    """使用指定模型配置创建 Agent。"""
    if model_config is None:
        model_config = get_active_model()

    if not model_config:
        return None

    api_key = model_config.get("api_key") or CONFIG.get("minimax_api_key", "")
    api_base = model_config.get("api_base") or CONFIG.get("minimax_api_base", "https://api.minimaxi.com/v1")
    model_name = model_config.get("name", "MiniMax-M2.7")
    temperature = model_config.get("temperature", 0.7)

    if not api_key:
        return None

    return create_agent(
        model_name=model_name,
        api_key=api_key,
        api_base=api_base,
        temperature=temperature,
        mcp_tools=mcp_tools or [],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化，关闭时清理。"""
    global _agent, _mcp_tools, _wechat_executor, _main_loop
    # 保存主事件循环引用，供子线程提交协程使用
    _main_loop = asyncio.get_running_loop()
    app.state.main_loop = _main_loop
    # 初始化数据库
    from .db import init_db

    init_db()
    # 检查是否启用 MCP（通过环境变量控制）
    if os.environ.get("NEXUS_ENABLE_MCP", "true").lower() == "true":
        _mcp_tools = await load_all_mcp_tools()
    else:
        _mcp_tools = []
        logger.info("MCP 功能已禁用")
    _agent = _create_agent_with_model(mcp_tools=_mcp_tools)
    # 注入共享依赖到 model_config 路由
    model_config_routes.init_router(
        agent_lock=_agent_lock,
        mcp_tools=_mcp_tools,
        create_agent_with_model=_create_agent_with_model,
        set_global_agent=_set_global_agent,
    )
    # 初始化通道注册表（lifespan 必须设置，否则 /api/channels 会 500）
    from .channels import ChannelRegistry

    app.state.channel_registry = ChannelRegistry()
    logger.info(f"Nexus Backend 已初始化 (MCP 工具: {len(_mcp_tools)} 个)")
    yield
    logger.info("Nexus Backend 关闭中")
    # 清理线程池
    if _wechat_executor:
        _wechat_executor.shutdown(wait=False)
        _wechat_executor = None


app = FastAPI(title="Nexus Backend", lifespan=lifespan)


def _set_global_agent(agent) -> None:
    """线程安全地替换全局 Agent 实例。供子模块（如 model_config 路由）调用。"""
    global _agent
    with _agent_lock:
        _agent = agent


API_PREFIX = "/api"

# 注册会话路由
app.include_router(sessions_router)
# 注册模型配置路由
app.include_router(model_config_routes.router)

# CORS 白名单：环境变量 NEXUS_ALLOWED_ORIGINS 逗号分隔；默认本地开发地址
_cors_origins = [
    o.strip()
    for o in os.environ.get(
        "NEXUS_ALLOWED_ORIGINS",
        "http://localhost:30077,http://127.0.0.1:30077,http://localhost:8000,http://127.0.0.1:8000,tauri://localhost",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态文件（挂载到 /app 路径避免与 API 冲突）
frontend_path = _get_frontend_path()
if frontend_path:
    app.mount("/app", StaticFiles(directory=str(frontend_path), html=True), name="static")

    # 根路径重定向到 /app
    @app.get("/")
    async def root_redirect():
        from starlette.responses import RedirectResponse

        return RedirectResponse(url="/app", status_code=302)


@app.get(f"{API_PREFIX}/")
async def root():
    return {"message": "Nexus Backend", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check():
    """健康检查端点（供 Docker 和外部监控使用）。"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": int(__import__("time").time()),
    }


@app.get(f"{API_PREFIX}/context")
async def get_context_info():
    """获取上下文窗口使用信息。

    返回：
    - max_tokens: 模型最大 context window
    - trigger_threshold: 触发压缩的阈值
    - usage_percent: 当前使用百分比（估算）
    """

    # 获取模型配置
    active = get_active_model()
    max_tokens = 200000
    if active:
        max_tokens = active.get("max_context_tokens", 200000)

    trigger_threshold = int(max_tokens * 0.85)

    return {
        "max_tokens": max_tokens,
        "trigger_threshold": trigger_threshold,
        "trigger_percent": 85,
        "keep_messages": 15,
        "offload_path": "~/.nexus/store/conversation_history",
    }


@app.post(f"{API_PREFIX}/context/compact")
async def trigger_compact():
    """手动触发上下文压缩（类似 Claude Code 的 /compact）。

    注意：当前实现由前端控制，实际压缩由 SummarizationMiddleware
    在下一轮对话时自动触发。
    """
    return {
        "success": True,
        "message": "上下文压缩已触发，将在下一轮对话时生效",
    }


@app.get(f"{API_PREFIX}/model")
async def get_model_info():
    """获取当前激活的模型信息。"""
    active = get_active_model()
    if active:
        return {
            "model_name": active.get("name", "MiniMax-M2.7"),
            "temperature": active.get("temperature", 0.7),
            "api_base": active.get("api_base", CONFIG["minimax_api_base"]),
            "id": active.get("id"),
            "max_context_tokens": active.get("max_context_tokens", 200000),
        }
    return {
        "model_name": CONFIG["model_name"],
        "temperature": CONFIG["temperature"],
        "api_base": CONFIG["minimax_api_base"],
    }


def _estimate_tokens(text: str) -> tuple[int, int]:
    """估算 token 数量和上下文使用率。

    Args:
        text: 文本内容

    Returns:
        (token_count, context_usage_percent)
    """
    chinese_chars = len(re.findall(r"[一-鿿]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    other_chars = len(text) - chinese_chars - english_chars
    estimated_tokens = int(chinese_chars * 2.5 + english_chars * 0.25 + other_chars * 0.5)
    context_usage = min(int((estimated_tokens / 200000) * 100), 100)
    return estimated_tokens, context_usage


def _extract_request_token(request: Request) -> str:
    """从 header / query 提取 token；REST 鉴权用。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "")


def require_token(request: Request) -> None:
    """FastAPI 依赖：校验 REST 请求 token。失败抛 401。"""
    token = _extract_request_token(request)
    expected = CONFIG.get("ws_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="未授权")


@app.websocket(f"{API_PREFIX}/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token != CONFIG.get("ws_token", ""):
        await websocket.close(code=4001, reason="未授权")
        return

    await websocket.accept()

    # 注册客户端
    with _clients_lock:
        _ws_clients.append(websocket)

    # 设置微信消息回调
    from .channels.wechat import get_active_wechat_channel

    channel = get_active_wechat_channel()
    if channel:
        channel.on_message(_handle_wechat_message)

    # 会话管理
    from .sessions import get_session_manager

    session_manager = get_session_manager()
    session_id = None

    try:
        while True:
            data = await websocket.receive_json()
            user_content = data.get("content", "")

            if not user_content:
                continue

            # 创建或获取会话
            new_session_created = False
            if session_id is None:
                session_id = data.get("session_id")
                if not session_id:
                    from .db import create_session

                    session_id = str(uuid.uuid4())
                    title = data.get("title") or "新会话"
                    create_session(session_id, title=title, channel="main")
                    new_session_created = True

            if new_session_created:
                await websocket.send_json(
                    {
                        "type": "session_created",
                        "session_id": session_id,
                        "title": title,
                    }
                )

            # 添加用户消息到历史
            from .db import add_message

            add_message(str(uuid.uuid4()), session_id, "user", user_content)

            # 使用 SessionManager 构建带记忆的 prompt
            prompt = session_manager.build_prompt(session_id, user_content)

            full_response = ""

            try:
                with _agent_lock:
                    agent = _agent
                async for chunk in agent.astream({"messages": prompt["messages"]}, stream_mode="updates"):
                    if not isinstance(chunk, dict):
                        continue

                    if "model" in chunk:
                        model_data = chunk.get("model")
                        if model_data and isinstance(model_data, dict):
                            messages = model_data.get("messages", [])
                            for msg in messages:
                                msg_content = getattr(msg, "content", "") or ""
                                if msg_content:
                                    full_response += msg_content

                    elif "tool_call" in chunk:
                        tool_name = chunk.get("tool_call", {}).get("name", "未知工具")
                        await websocket.send_json(
                            {
                                "type": "thinking",
                                "content": f"[调用工具] {tool_name}",
                            }
                        )

                    elif "tool_result" in chunk:
                        result = chunk.get("tool_result", "")
                        await websocket.send_json(
                            {
                                "type": "thinking",
                                "content": f"[工具返回] {str(result)[:100]}...",
                            }
                        )

                normalized = full_response.replace("<think>", "<thinking>").replace("</think>", "</thinking>")

                estimated_tokens, context_usage = _estimate_tokens(normalized)

                await websocket.send_json(
                    {
                        "type": "token_usage",
                        "content": "",
                        "token_count": estimated_tokens,
                        "context_usage": context_usage,
                    }
                )

                thinking_parts = re.findall(r"<thinking>(.*?)</thinking>", normalized, flags=re.DOTALL)
                response_text = re.sub(r"<thinking>.*?</thinking>", "", normalized, flags=re.DOTALL).strip()

                if thinking_parts:
                    all_thinking = "\n".join(part.strip() for part in thinking_parts)
                    await websocket.send_json(
                        {
                            "type": "thinking",
                            "content": all_thinking,
                        }
                    )

                if response_text:
                    # 分块发送：每帧约 16 字符（约 4-5 个 token），UI 打字效果更顺滑
                    chunk_size = 16
                    for i in range(0, len(response_text), chunk_size):
                        chunk = response_text[i : i + chunk_size]
                        await websocket.send_json(
                            {
                                "type": "chunk",
                                "content": chunk,
                            }
                        )

                    await websocket.send_json(
                        {
                            "type": "final",
                            "content": response_text,
                        }
                    )

                await websocket.send_json(
                    {
                        "type": "done",
                        "content": "",
                    }
                )

                # 保存助手回复到数据库
                if response_text:
                    add_message(str(uuid.uuid4()), session_id, "assistant", full_response)

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Agent error: {error_msg}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": error_msg,
                    }
                )

    except WebSocketDisconnect:
        logger.info("客户端断开连接")
        with _clients_lock:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)


# ========== 微信通道 API ==========


@app.post(f"{API_PREFIX}/channels/wechat/qr")
async def wechat_qr_login():
    """获取微信登录二维码"""
    from .channels.wechat import wechat_qr_login as do_qr_login

    try:
        result = await do_qr_login()
        return result
    except Exception as e:
        logger.error(f"WeChat QR login failed: {e}")
        return {"success": False, "error": str(e)}


@app.get(f"{API_PREFIX}/channels/wechat/status/{{session_key}}")
async def wechat_qr_status(session_key: str, timeout_ms: int = 10000):
    """获取微信登录二维码状态"""
    from .channels.wechat import wait_qr_scan

    try:
        result = await wait_qr_scan(session_key, timeout_ms=timeout_ms)
        return result
    except Exception as e:
        logger.error(f"WeChat QR status check failed: {e}")
        return {"success": False, "error": str(e)}


@app.get(f"{API_PREFIX}/channels/wechat/bind")
async def wechat_bind_status():
    """获取微信绑定状态"""
    from .channels.wechat import _list_indexed_weixin_account_ids, _load_account, get_active_wechat_channel

    # 检查是否有活跃通道
    channel = get_active_wechat_channel()
    if channel and channel._account:
        return {
            "bound": True,
            "account_id": channel._account.account_id,
            "status": channel.state.status.value if hasattr(channel.state, "status") else "running",
        }

    # 检查是否有已保存的账号
    account_ids = _list_indexed_weixin_account_ids()
    if account_ids:
        # 加载最近的账号
        account_id = account_ids[0]
        account = _load_account(account_id)
        if account:
            return {
                "bound": True,
                "account_id": account_id,
                "status": "stopped",
            }

    return {
        "bound": False,
    }


@app.post(f"{API_PREFIX}/channels/wechat/bind")
async def wechat_do_bind():
    """绑定微信账号"""
    from .channels.wechat import (
        ChannelConfig,
        ChannelType,
        _delete_account,
        _list_indexed_weixin_account_ids,
        _load_account,
        get_active_wechat_channel,
    )

    # 检查是否已有活跃通道
    channel = get_active_wechat_channel()
    if channel and channel._account:
        return {
            "success": True,
            "bound": True,
            "account_id": channel._account.account_id,
        }

    # 检查是否有已保存的账号
    account_ids = _list_indexed_weixin_account_ids()
    if account_ids:
        account_id = account_ids[0]
        account = _load_account(account_id)
        if account:
            # 创建并启动通道
            config = ChannelConfig(
                channel_id=f"wechat:{account_id}",
                channel_type=ChannelType.WECHAT,
                name=f"WeChat ({account_id[:8]}...)",
                settings={"account_id": account_id},
            )
            from .channels.wechat import WeChatChannel as WCH  # noqa: N814
            from .channels.wechat import _check_token_valid

            # 先检查 token 是否有效
            if not _check_token_valid(account_id):
                # token 过期，删除旧数据
                _delete_account(account_id)
                return {
                    "success": False,
                    "bound": False,
                    "error": "登录已过期，请重新扫码绑定",
                    "need_rescan": True,
                }

            logger.debug(f"Token valid for account {account_id}, creating channel")
            # token 有效，创建并启动通道
            new_channel = WCH(config, token=account_id)
            logger.debug(f"About to start channel for account {account_id}")
            await new_channel.start()
            logger.debug("Channel started, about to set on_message callback")
            new_channel.on_message(_handle_wechat_message)
            logger.debug("on_message callback set successfully")

            from .channels.wechat import _set_active_channel

            _set_active_channel(new_channel)
            logger.info(f"Active channel set for account {account_id}")

            return {
                "success": True,
                "bound": True,
                "account_id": account_id,
            }

    return {
        "success": False,
        "error": "请先扫码绑定微信",
    }


@app.delete(f"{API_PREFIX}/channels/wechat/bind")
async def wechat_unbind():
    """解除微信绑定"""
    from .channels.wechat import _clear_active_channel, get_active_wechat_channel

    channel = get_active_wechat_channel()
    if channel:
        await channel.stop()

    _clear_active_channel()
    return {"success": True}


@app.get(f"{API_PREFIX}/channels")
async def get_channels(request: Request):
    """获取所有通道状态"""
    from .channels import ChannelRegistry

    registry: ChannelRegistry = request.app.state.channel_registry
    channels = []
    for ch in registry.list_all():
        channels.append(
            {
                "id": ch.id,
                "type": ch.type.value if hasattr(ch.type, "value") else str(ch.type),
                "status": ch.status.value if hasattr(ch.status, "value") else str(ch.status),
                "enabled": True,
            }
        )
    return {"channels": channels}
