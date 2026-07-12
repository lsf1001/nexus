import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .agent import _reset_checkpointer_cache, create_agent
from .api.ws import (
    _clients_lock,
    _extract_ws_token,
    _hmac_compare,
    _ws_clients,
    handle_websocket,
    require_token,
)
from .config import CONFIG
from .mcp import load_all_mcp_tools
from .models_config import get_active_model
from .observability import setup_logging
from .routes import model_config as model_config_routes
from .sessions import router as sessions_router

_agent = None
_mcp_tools: list[Any] = []
_agent_lock = threading.RLock()
# Agent 构造完成事件:WS 端在调 handle_websocket 前 await 这个,
# 避免首条消息到达时 _agent 仍为 None,被 _run_agent_streaming 拒为 agent_unavailable。
# 后台线程构造完成后 set;timeout 60s 后放弃,走原错误路径。
_agent_ready_event: asyncio.Event | None = None

_main_loop: asyncio.AbstractEventLoop | None = None


class _AgentProxy:
    """Gateway 需要 agent.astream(),但 agent 是懒构造。代理暴露 .astream 调用
    时的实时 agent 实例,使 Gateway 无需关心 agent 何时就绪。

    getter 在 lifespan 时尚未定义(WS 路由后才有),所以延迟到首次调用 .astream
    时通过 ``_resolve_getter`` 解析一次。Gateway 第一次收到消息已经在
    WS 已连接 + agent 已懒构造 之后,_resolve_getter 返回真实 getter。
    """

    def __init__(self, resolve_getter):
        self._resolve_getter = resolve_getter
        self._getter = None

    def astream(self, input_dict, stream_mode="updates"):
        if self._getter is None:
            self._getter = self._resolve_getter()
        agent = self._getter()
        if agent is None:
            raise RuntimeError("Agent 未就绪,请稍后再试")
        return agent.astream(input_dict, stream_mode=stream_mode)


setup_logging()  # env 驱动:NEXUS_LOG_FORMAT/FILE/LEVEL
logger = logging.getLogger(__name__)


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
    global _agent, _mcp_tools, _main_loop
    # 保存主事件循环引用，供子线程提交协程使用
    _main_loop = asyncio.get_running_loop()
    app.state.main_loop = _main_loop
    global _app_ref
    _app_ref = app  # 给懒构造的 _ensure_agent_async 复用
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

    # 初始化 Gateway + ChannelRegistry (C4 重构: Gateway 真接管路由)
    import nexus.backend.db as _db_module

    from .channels import ChannelRegistry, Gateway
    from .sessions import get_session_manager

    sessions_module = get_session_manager()
    app.state.gateway = Gateway(
        agent=_AgentProxy(lambda: _get_current_agent),
        sessions_module=sessions_module,
        messages_module=_db_module,
    )
    app.state.channel_registry = ChannelRegistry(app.state.gateway)
    # QualityPipeline 也延后到 agent 构造完后再做（依赖 judge_llm）
    app.state.quality_pipeline = None
    logger.info("Nexus Backend 已就绪 (Gateway 接管路由, Agent 懒构造)")
    yield
    logger.info("Nexus Backend 关闭中")
    _reset_checkpointer_cache()


def _ensure_agent_ready(app) -> None:
    """懒构造 Agent：首次调用时同步阻塞完成。

    由于构造过程涉及 langchain / deepagents 的大量 import，无法在 async 上下文
    内 await。调用方应在第一次 WS 消息到达前在独立线程触发它，构造完成后
    主流程直接使用 _agent。

    2026-06-29 重构:IntentClassifier 自造模块已删除(intent/router.py 改用
    正则),judge_llm 也不再需要。质量门走 deepagents RubricMiddleware
    (见 agent.py QualityGateMiddleware + MemoryFilter)。本函数只构造
    Agent + MCP,不再附加 LLM 全局。
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
                logger.warning("MCP 加载失败，继续启动: %s", e, exc_info=True)
                _mcp_tools = []
        new_agent = _create_agent_with_model(mcp_tools=_mcp_tools)
        if new_agent is not None:
            _agent = new_agent


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
# allow_credentials=True 时不允许 origin="*" (CORS 规范),
# 生产部署若有人误把 NEXUS_ALLOWED_ORIGINS 设成 * 直接启动失败
if any(o == "*" for o in _cors_origins):
    raise ValueError(
        "NEXUS_ALLOWED_ORIGINS 不允许包含 '*' (allow_credentials=True 不兼容通配 origin),"
        "请使用显式 origin 列表,如 'http://localhost:30077,tauri://localhost'"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
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
async def root() -> dict[str, str]:
    """API 根端点,返回服务基本信息(版本 / 运行状态)。"""
    return {"message": "Nexus Backend", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """健康检查端点（供 Docker 和外部监控使用）。"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": int(__import__("time").time()),
    }


@app.get(f"{API_PREFIX}/context", dependencies=[Depends(require_token)])
async def get_context_info() -> dict[str, Any]:
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
async def trigger_compact() -> dict[str, Any]:
    """手动触发上下文压缩（类似 Claude Code 的 /compact）。

    注意：当前实现由前端控制，实际压缩由 SummarizationMiddleware
    在下一轮对话时自动触发。
    """
    return {
        "success": True,
        "message": "上下文压缩已触发，将在下一轮对话时生效",
    }


@app.get(f"{API_PREFIX}/model", dependencies=[Depends(require_token)])
async def get_model_info() -> dict[str, Any]:
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


_agent_init_started = False
_app_ref: FastAPI | None = None


def _ensure_agent_async(app) -> None:
    """懒构造 Agent：在子线程里跑，构造期间 /health 已经能 200。
    用一次性触发：一旦构造过就 noop。
    """
    global _agent_init_started, _agent_ready_event
    with _agent_lock:
        if _agent is not None or _agent_init_started:
            return
        _agent_init_started = True
    if _agent_ready_event is None:
        _agent_ready_event = asyncio.Event()

    def _run_init_and_signal() -> None:
        try:
            _ensure_agent_ready(app)
        finally:
            # 跨线程设置 asyncio.Event:必须用 call_soon_threadsafe
            if _main_loop and not _main_loop.is_closed() and _agent_ready_event is not None:
                _main_loop.call_soon_threadsafe(_agent_ready_event.set)

    threading.Thread(
        target=_run_init_and_signal,
        name="nexus-agent-init",
        daemon=True,
    ).start()


def _get_current_agent() -> Any:
    """返回当前 agent。Agent 尚未构造时返回 None;Gateway 走 astream 时
    会拿到 None → RuntimeError → 走 _send_error 错误路径(同 WS 行为)。

    入口兜底:WS 端 / Gateway 首次调用此函数都会触发 _ensure_agent_async,
    确保 WeChat 消息先于 WS 连接到达时也能进入懒构造路径。
    模块级函数,供 _AgentProxy 在 lifespan 后通过 lambda: _get_current_agent 解析。
    """
    if _agent is None and not _agent_init_started and _app_ref is not None:
        _ensure_agent_async(_app_ref)
    with _agent_lock:
        return _agent


def _build_broadcast_to_ws(websocket: WebSocket):
    """工厂:给当前 WS 连接生成一个 Gateway 广播回调。
    Gateway.route_message 走完后会用此回调,把 ChannelMessage 转成 channel_message 帧。
    """

    async def _broadcast_to_ws(channel_msg) -> None:
        frame = {
            "type": "channel_message",
            "channel_type": channel_msg.channel_type.value,
            "channel_id": channel_msg.channel_id,
            "user_id": channel_msg.user_id,
            "content": channel_msg.content,
            "session_id": channel_msg.session_id,
        }
        with _clients_lock:
            clients = list(_ws_clients)
        for client in clients:
            try:
                await client.send_json(frame)
            except Exception as e:
                logger.warning(f"广播失败: {e}")

    return _broadcast_to_ws


@app.websocket(f"{API_PREFIX}/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 主端点：业务逻辑委托给 ``api.ws.handle_websocket``。

    鉴权(2026-07 改造,见 :func:`nexus.backend.api.ws.auth._extract_ws_token`):

    - 优先读 ``Sec-WebSocket-Protocol`` 头里 ``nexus-v1.token=<value>``,
      token 不进 URL,不进代理 access log / 浏览器历史 / 错误堆栈。
    - Fallback 读 ``?token=`` query string,由 ``NEXUS_WS_AUTH_QUERY_FALLBACK``
      控制开关(默认 ``true``,下个 major 版本移除)。
    - 任何路径都走 ``hmac.compare_digest`` 做常量时间比较,防时序攻击。
    """
    expected = CONFIG.get("ws_token", "")
    token = _extract_ws_token(websocket)
    if not _hmac_compare(token, expected):
        await websocket.close(code=4001, reason="未授权")
        return

    # 选 subprotocol 时 echo 回客户端;若客户端用 fallback query,无 subprotocol 可选。
    selected_subprotocol = "nexus-v1"
    header_value = websocket.headers.get("sec-websocket-protocol", "")
    has_nexus_subprotocol = any(p.strip().startswith("nexus-v1.token=") for p in header_value.split(","))
    if has_nexus_subprotocol:
        await websocket.accept(subprotocol=selected_subprotocol)
    else:
        await websocket.accept()

    # 懒构造 Agent：在子线程里跑，构造期间 /health 已经能 200。
    # 用一次性触发：一旦构造过就 noop。
    _ensure_agent_async(websocket.app)

    # 等 Agent 构造完成(首启 / PyInstaller 冷启场景下 10-30s 是常态)。
    # 2026-07-12 Plan 3 Phase 4:60s 超时后**不**断 WS,改发 system 帧
    # {type:'system', payload:{event:'agent_init_timeout', retry_in:5}}
    # 客户端(Plan 3 WsClient)收到此帧后会临时拉长 baseDelay 5s 做退避
    # hint,WS 自身仍保持连接 — 用户首条消息走 agent_unavailable 错误路径。
    if _agent is None and _agent_ready_event is not None:
        try:
            await asyncio.wait_for(_agent_ready_event.wait(), timeout=60.0)
        except TimeoutError:
            logger.warning("Agent 懒构造 60s 超时,发送 system 帧给客户端作 retry hint")
            try:
                await websocket.send_json(
                    {
                        "type": "system",
                        "payload": {"event": "agent_init_timeout", "retry_in": 5},
                    }
                )
            except Exception as e:  # noqa: BLE001 — send_json 失败时连接可能已断,吞掉
                logger.warning(f"发送 agent_init_timeout 帧失败(WS 可能已断): {e}")

    def _get_quality_pipeline() -> Any:
        # 2026-06-29 重构:QualityPipeline 已删除,质量门由 deepagents RubricMiddleware
        # 在 agent 内部驱动。返回 None 让 ws.py 的 no-op 分支接管。
        return None

    await handle_websocket(
        websocket,
        get_agent=_get_current_agent,
        channel_broadcasts={"wechat": _build_broadcast_to_ws(websocket)},
        get_quality_pipeline=_get_quality_pipeline,
    )


# ========== 微信通道 API ==========


@app.post(f"{API_PREFIX}/channels/wechat/qr", dependencies=[Depends(require_token)])
async def wechat_qr_login(request: Request) -> dict[str, Any]:
    """获取微信登录二维码"""
    from .channels.wechat_login import wechat_qr_login as do_qr_login

    try:
        result = await do_qr_login(request.app.state.channel_registry)
        return result
    except Exception as e:
        logger.error(f"WeChat QR login failed: {e}")
        return {"success": False, "error": str(e)}


@app.get(f"{API_PREFIX}/channels/wechat/status/{{session_key}}", dependencies=[Depends(require_token)])
async def wechat_qr_status(request: Request, session_key: str, timeout_ms: int = 10000) -> dict[str, Any]:
    """获取微信登录二维码状态"""
    from .channels.wechat_login import wait_qr_scan

    try:
        result = await wait_qr_scan(session_key, request.app.state.channel_registry, timeout_ms=timeout_ms)
        return result
    except Exception as e:
        logger.error(f"WeChat QR status check failed: {e}")
        return {"success": False, "error": str(e)}


@app.get(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_bind_status(request: Request) -> dict[str, Any]:
    """获取微信绑定状态"""
    from .channels.base import ChannelType
    from .channels.wechat_account import (
        _list_indexed_weixin_account_ids,
        _load_account,
    )

    registry = request.app.state.channel_registry
    active = registry.get_active_by_type(ChannelType.WECHAT)
    if active and getattr(active, "_account", None):
        return {
            "bound": True,
            "account_id": active._account.account_id,
            "status": active.state.status.value,
        }
    account_ids = _list_indexed_weixin_account_ids()
    if account_ids:
        account_id = account_ids[0]
        account = _load_account(account_id)
        if account:
            return {"bound": True, "account_id": account_id, "status": "stopped"}
    return {"bound": False}


@app.post(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_do_bind(request: Request) -> dict[str, Any]:
    """绑定微信账号:从已有账号恢复,或要求重新扫码。"""
    from .channels.base import ChannelConfig, ChannelType
    from .channels.wechat_account import (
        _check_token_valid,
        _delete_account,
        _list_indexed_weixin_account_ids,
        _load_account,
    )

    registry = request.app.state.channel_registry
    active = registry.get_active_by_type(ChannelType.WECHAT)
    if active and getattr(active, "_account", None):
        return {
            "success": True,
            "bound": True,
            "account_id": active._account.account_id,
        }
    account_ids = _list_indexed_weixin_account_ids()
    if not account_ids:
        return {"success": False, "error": "请先扫码绑定微信"}
    account_id = account_ids[0]
    account = _load_account(account_id)
    if not account:
        return {"success": False, "error": "账号已损坏,请重新扫码"}
    if not _check_token_valid(account_id):
        _delete_account(account_id)
        return {
            "success": False,
            "bound": False,
            "error": "登录已过期,请重新扫码绑定",
            "need_rescan": True,
        }
    config = ChannelConfig(
        channel_id=f"wechat:{account_id}",
        channel_type=ChannelType.WECHAT,
        name=f"WeChat ({account_id[:8]}...)",
        settings={"account_id": account_id},
    )
    await registry.start_channel(config, token=account_id)
    return {"success": True, "bound": True, "account_id": account_id}


@app.delete(f"{API_PREFIX}/channels/wechat/bind", dependencies=[Depends(require_token)])
async def wechat_unbind(request: Request) -> dict[str, bool]:
    """解除微信绑定"""
    from .channels.base import ChannelType

    registry = request.app.state.channel_registry
    active = registry.get_active_by_type(ChannelType.WECHAT)
    if active:
        await registry.stop_channel(active.config.channel_id)
    return {"success": True}


@app.get(f"{API_PREFIX}/channels", dependencies=[Depends(require_token)])
async def get_channels(request: Request) -> dict[str, list[dict[str, Any]]]:
    """获取所有通道状态"""
    from .channels import ChannelRegistry

    registry: ChannelRegistry = request.app.state.channel_registry
    channels = []
    for ch in registry.list_all():
        channels.append(
            {
                "id": ch.get_channel_id(),
                "type": ch.get_channel_type().value,
                "status": ch.get_status().value,
                "enabled": True,
            }
        )
    return {"channels": channels}
