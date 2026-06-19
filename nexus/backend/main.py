import asyncio
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .agent import create_agent
from .api.ws import (
    _clients_lock,
    _ws_clients,
    handle_websocket,
    require_token,
)
from .config import CONFIG
from .mcp import load_all_mcp_tools
from .models_config import get_active_model
from .routes import model_config as model_config_routes
from .sessions import router as sessions_router

_agent = None
_mcp_tools: list[Any] = []
_agent_lock = threading.RLock()
# Agent 构造完成事件:WS 端在调 handle_websocket 前 await 这个,
# 避免首条消息到达时 _agent 仍为 None,被 _run_agent_streaming 拒为 agent_unavailable。
# 后台线程构造完成后 set;timeout 60s 后放弃,走原错误路径。
_agent_ready_event: asyncio.Event | None = None

# 微信消息处理线程池（全局复用）
_wechat_executor: ThreadPoolExecutor | None = None
_main_loop: asyncio.AbstractEventLoop | None = None

# 微信用户 session 映射（user_id -> session_id）
# 关键不变量：
#   1. 同一 user_id 的两个并发消息不能创建两个 session → 必须用 asyncio.Lock 串行化
#   2. 后端重启时 in-memory 映射丢失，但 DB 里 channel='wechat' 的旧 session 还在
#      → 启动时按"该 user_id 最近一次 wechat session"重建映射
_wechat_sessions: dict[str, str] = {}  # user_id -> session_id
_wechat_sessions_lock: asyncio.Lock | None = None  # 在 lifespan 内初始化


async def _resolve_wechat_session(user_id: str, account_id: str) -> str:
    """在 asyncio.Lock 内调用：获取或创建 user_id 对应的 wechat session。

    查找顺序：in-memory 映射 → DB 持久化映射（按"该 user_id 最近一条 wechat 消息
    所属的 session"重建）→ 新建 session。
    """
    from .db import create_session, find_latest_session_by_user, get_session

    # 1) in-memory 命中且 DB 仍有 → 复用
    if user_id in _wechat_sessions:
        existing_session_id = _wechat_sessions[user_id]
        if get_session(existing_session_id):
            return existing_session_id
        # 内存有但 DB 已删 → 走 DB 重建
        del _wechat_sessions[user_id]

    # 2) DB 重建：找该 user_id 最近一次 wechat 消息所属的 session
    db_session_id = find_latest_session_by_user(user_id, channel="wechat")
    if db_session_id and get_session(db_session_id):
        _wechat_sessions[user_id] = db_session_id
        logger.info("Resumed WeChat session for %s from DB: %s", user_id, db_session_id)
        return db_session_id

    # 3) 都没有 → 新建
    session_id = str(uuid.uuid4())
    wx_id = user_id.split("@")[0][:8]
    acc_id = account_id[:8]
    title = f"微信 {acc_id} {wx_id}"
    create_session(session_id, title=title, channel="wechat")
    _wechat_sessions[user_id] = session_id
    logger.info("Created session for WeChat user %s: %s", user_id, session_id)
    return session_id


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

        with _clients_lock:
            clients = list(_ws_clients)

        logger.info(f"WebSocket clients: {len(clients)}")

        # 构造广播帧：前端 ChatArea / DesktopShell 的 wechatInbox store 订阅此类型。
        message_data = {
            "type": "wechat_message",
            "user_id": channel_message.user_id,
            "content": channel_message.content,
        }

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

        # 获取或创建会话（在 asyncio.Lock 内串行化，避免同一 user_id 并发双建 session）
        user_id = channel_message.user_id
        account_id = channel._account.account_id if channel._account else "unknown"

        if _wechat_sessions_lock is None:
            # lifespan 还没跑（极端：测试/热重载）→ 退化用无锁路径
            session_id = await _resolve_wechat_session(user_id, account_id)
        else:
            async with _wechat_sessions_lock:
                session_id = await _resolve_wechat_session(user_id, account_id)

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
    env_frontend = os.environ.get("NEXUS_FRONTEND_DIST")
    if env_frontend:
        frontend_path = Path(env_frontend).expanduser()
        if frontend_path.exists():
            return frontend_path

    nexus_home = Path(os.environ.get("NEXUS_HOME", str(Path.home() / ".nexus"))).expanduser()
    frontend_path = nexus_home / "frontend" / "dist"
    if frontend_path.exists():
        return frontend_path

    legacy_frontend = Path.home() / ".nexus" / "frontend" / "dist"
    if legacy_frontend.exists():
        return legacy_frontend

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
    model_name = model_config.get("name", "MiniMax-M3")
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
    """启动时初始化，关闭时清理。

    性能关键：Agent / QualityPipeline 的构造（import langchain / deepagents /
    编译 LangGraph 图）耗时在 PyInstaller 打包后会被放大 10-30x。把这部分
    从 lifespan 推到首次使用时，/health 在 1-2s 内就能响应 → 桌面端无需
    等待 30s 就能加载 UI。Agent / pipeline 走"懒构造"路径。
    """
    global _agent, _mcp_tools, _wechat_executor, _main_loop, _wechat_sessions_lock
    # 保存主事件循环引用，供子线程提交协程使用
    _main_loop = asyncio.get_running_loop()
    app.state.main_loop = _main_loop
    # 初始化 asyncio.Lock：用于 _wechat_sessions 字典的并发读写。
    # 必须在 lifespan 内创建（绑定到主事件循环），否则在子线程中 asyncio.Lock()
    # 绑定到子线程的事件循环会出错。
    _wechat_sessions_lock = asyncio.Lock()
    # 初始化数据库
    from .db import init_db

    init_db()
    # MCP 加载延后到 agent 首次构造时（省 0.5-3s）
    _mcp_tools = []
    # 关键：_agent 不在 lifespan 内构造。首次 WS 消息 / setup 完成时
    # 走 _ensure_agent_ready() 触发构造。期间 /health / REST 路由正常工作。
    _agent = None
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
    # QualityPipeline 也延后到 agent 构造完后再做（依赖 judge_llm）
    app.state.quality_pipeline = None
    logger.info("Nexus Backend 已就绪（Agent 懒构造）")
    yield
    logger.info("Nexus Backend 关闭中")
    # 清理线程池
    if _wechat_executor:
        _wechat_executor.shutdown(wait=False)
        _wechat_executor = None
    # 重置 lock 和 in-memory 状态，避免热重载残留
    _wechat_sessions_lock = None
    _wechat_sessions.clear()


def _ensure_agent_ready(app) -> None:
    """懒构造 Agent：首次调用时同步阻塞完成。

    由于构造过程涉及 langchain / deepagents 的大量 import，无法在 async 上下文
    内 await。调用方应在第一次 WS 消息到达前在独立线程触发它，构造完成后
    主流程直接使用 _agent。
    """
    global _agent, _mcp_tools
    with _agent_lock:
        if _agent is not None:
            return
        import os

        if not _mcp_tools and os.environ.get("NEXUS_ENABLE_MCP", "true").lower() == "true":
            try:
                _mcp_tools = asyncio.run_coroutine_threadsafe(load_all_mcp_tools(), _main_loop).result(timeout=10)
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP 加载失败，继续启动: %s", e)
                _mcp_tools = []
        new_agent = _create_agent_with_model(mcp_tools=_mcp_tools)
        if new_agent is not None:
            _agent = new_agent
        # 构造 QualityPipeline
        try:
            from .agent import get_llm
            from .quality.pipeline import QualityPipeline
            from .rubrics.judge import RubricJudge
            from .rubrics.prompts import apply_prompts_to_default_rubrics
            from .rubrics.repair import RepairStrategy

            apply_prompts_to_default_rubrics()
            from .models_config import get_active_model as _get_active_model

            _model_config = _get_active_model() or {}
            judge_api_key = _model_config.get("api_key") or CONFIG.get("minimax_api_key", "")
            if judge_api_key:
                # judge LLM 固定 temperature=0:质量门是确定性评估,同样的 raw_response
                # 应该稳定产出同样的 verdict。沿用主对话 0.7 会让 ACCEPT/REPAIR/REJECT
                # 在边界态反复横跳,影响 quality gate 稳定性(repair 重生也会跟着抖动)。
                # 主对话 LLM 是另一个独立实例(new_agent 内部用 get_llm(temperature=0.7)
                # 构造),互不影响。
                judge_llm = get_llm(
                    api_key=judge_api_key,
                    api_base=_model_config.get("api_base") or CONFIG.get("minimax_api_base"),
                    model_name=_model_config.get("name", CONFIG.get("model_name", "MiniMax-M3")),
                    temperature=0,
                )
                app.state.quality_pipeline = QualityPipeline(
                    judge=RubricJudge(llm=judge_llm),
                    repair_strategy=RepairStrategy(),
                    main_llm=judge_llm,
                )
                logger.info("QualityPipeline 已就绪")
            else:
                logger.info("未配置 API Key，质量门已跳过")
        except Exception as e:  # noqa: BLE001
            logger.warning("QualityPipeline 构造失败，已跳过: %s", e)


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


@app.get(f"{API_PREFIX}/context", dependencies=[Depends(require_token)])
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


@app.post(f"{API_PREFIX}/context/compact", dependencies=[Depends(require_token)])
async def trigger_compact():
    """手动触发上下文压缩（类似 Claude Code 的 /compact）。

    注意：当前实现由前端控制，实际压缩由 SummarizationMiddleware
    在下一轮对话时自动触发。
    """
    return {
        "success": True,
        "message": "上下文压缩已触发，将在下一轮对话时生效",
    }


@app.get(f"{API_PREFIX}/model", dependencies=[Depends(require_token)])
async def get_model_info():
    """获取当前激活的模型信息。"""
    active = get_active_model()
    if active:
        return {
            "model_name": active.get("name", "MiniMax-M3"),
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


@app.websocket(f"{API_PREFIX}/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 主端点：业务逻辑委托给 ``api.ws.handle_websocket``。"""
    token = websocket.query_params.get("token")
    if token != CONFIG.get("ws_token", ""):
        await websocket.close(code=4001, reason="未授权")
        return

    await websocket.accept()

    # 懒构造 Agent：在子线程里跑，构造期间 /health 已经能 200。
    # 用一次性触发：一旦构造过就 noop。
    _agent_init_started = False

    def _ensure_agent_async() -> None:
        nonlocal _agent_init_started
        global _agent_ready_event
        with _agent_lock:
            if _agent is not None or _agent_init_started:
                return
            _agent_init_started = True
        if _agent_ready_event is None:
            _agent_ready_event = asyncio.Event()
        import threading

        def _run_init_and_signal() -> None:
            try:
                _ensure_agent_ready(websocket.app)
            finally:
                # 跨线程设置 asyncio.Event:必须用 call_soon_threadsafe
                if _main_loop and not _main_loop.is_closed() and _agent_ready_event is not None:
                    _main_loop.call_soon_threadsafe(_agent_ready_event.set)

        threading.Thread(
            target=_run_init_and_signal,
            name="nexus-agent-init",
            daemon=True,
        ).start()

    _ensure_agent_async()

    # 等 Agent 构造完成(首启 / PyInstaller 冷启场景下 10-30s 是常态)。
    # 设 60s 上限,极端慢盘 / MCP 加载失败场景下放弃,让 _run_agent_streaming
    # 走原 agent_unavailable 错误路径,而不是阻塞 WS 升级握手。
    if _agent is None and _agent_ready_event is not None:
        try:
            await asyncio.wait_for(_agent_ready_event.wait(), timeout=60.0)
        except TimeoutError:
            logger.warning("Agent 懒构造 60s 超时,首条消息将走 agent_unavailable 错误路径")

    def _get_current_agent() -> Any:
        # 触发懒构造（首次调用时启动后台线程）
        _ensure_agent_async()
        with _agent_lock:
            return _agent

    def _get_quality_pipeline() -> Any:
        return getattr(websocket.app.state, "quality_pipeline", None)

    await handle_websocket(
        websocket,
        get_agent=_get_current_agent,
        wechat_callback=_handle_wechat_message,
        get_quality_pipeline=_get_quality_pipeline,
    )


# ========== 微信通道 API ==========


@app.post(f"{API_PREFIX}/channels/wechat/qr", dependencies=[Depends(require_token)])
async def wechat_qr_login():
    """获取微信登录二维码"""
    from .channels.wechat import wechat_qr_login as do_qr_login

    try:
        result = await do_qr_login()
        return result
    except Exception as e:
        logger.error(f"WeChat QR login failed: {e}")
        return {"success": False, "error": str(e)}


@app.get(f"{API_PREFIX}/channels/wechat/status/{{session_key}}", dependencies=[Depends(require_token)])
async def wechat_qr_status(session_key: str, timeout_ms: int = 10000):
    """获取微信登录二维码状态"""
    from .channels.wechat import wait_qr_scan

    try:
        result = await wait_qr_scan(session_key, timeout_ms=timeout_ms)
        return result
    except Exception as e:
        logger.error(f"WeChat QR status check failed: {e}")
        return {"success": False, "error": str(e)}


@app.get(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
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


@app.post(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
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


@app.delete(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_unbind():
    """解除微信绑定"""
    from .channels.wechat import _clear_active_channel, get_active_wechat_channel

    channel = get_active_wechat_channel()
    if channel:
        await channel.stop()

    _clear_active_channel()
    return {"success": True}


@app.get(f"{API_PREFIX}/channels", dependencies=[Depends(require_token)])
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
