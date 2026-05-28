from contextlib import asynccontextmanager
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import CONFIG
from .agent import create_agent
from .models_config import load_models, get_active_model, set_active_model, save_models
from .mcp import load_all_mcp_tools
from .models import SwitchModelRequest, SwitchModelResponse

_agent = None
_mcp_tools: list[Any] = []
_agent_lock = threading.RLock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    global _agent, _mcp_tools
    # 检查是否启用 MCP（通过环境变量控制）
    if os.environ.get("NEXUS_ENABLE_MCP", "true").lower() == "true":
        _mcp_tools = await load_all_mcp_tools()
    else:
        _mcp_tools = []
        logger.info("MCP 功能已禁用")
    _agent = _create_agent_with_model(mcp_tools=_mcp_tools)
    logger.info(f"Nexus Backend 已初始化 (MCP 工具: {len(_mcp_tools)} 个)")
    yield
    logger.info("Nexus Backend 关闭中")


app = FastAPI(title="Nexus Backend", lifespan=lifespan)

API_PREFIX = "/api"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        }
    return {
        "model_name": CONFIG["model_name"],
        "temperature": CONFIG["temperature"],
        "api_base": CONFIG["minimax_api_base"],
    }


@app.get(f"{API_PREFIX}/models")
async def get_models():
    """获取所有模型列表。"""
    config = load_models()
    return config.get("models", [])


@app.post(f"{API_PREFIX}/models/switch", response_model=SwitchModelResponse)
async def switch_model(body: SwitchModelRequest):
    """切换当前激活的模型。"""
    global _agent
    model_id = body.id

    # 先加载配置，找到目标模型
    config = load_models()
    target = None
    for model in config.get("models", []):
        if model.get("id") == model_id:
            target = model
            break

    if not target:
        return SwitchModelResponse(success=False, error="模型不存在")

    # 检查 api_key 是否配置（检查后再设置激活状态）
    api_key = target.get("api_key")
    if not api_key:
        return SwitchModelResponse(success=False, error=f"模型 {target.get('name')} 未配置 API Key，无法使用")

    # 设置激活状态
    set_active_model(model_id)

    # 重新创建 Agent（保留 MCP 工具）
    new_agent = _create_agent_with_model(target, _mcp_tools)
    if new_agent is None:
        return SwitchModelResponse(success=False, error=f"模型 {target.get('name')} 配置无效，无法使用")

    with _agent_lock:
        global _agent
        _agent = new_agent

    return SwitchModelResponse(
        success=True,
        active_model={
            "id": target.get("id"),
            "name": target.get("name"),
        }
    )


class CreateModelRequest(BaseModel):
    """创建模型请求。"""
    id: str = Field(..., min_length=1, description="模型ID")
    name: str = Field(default="New Model", description="模型名称")
    api_key: str = Field(default="", description="API密钥")
    api_base: str = Field(default="https://api.minimaxi.com/v1", description="API端点")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")


class UpdateModelRequest(BaseModel):
    """更新模型请求。"""
    name: Optional[str] = Field(default=None, description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    api_base: Optional[str] = Field(default=None, description="API端点")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="温度参数")


@app.post(f"{API_PREFIX}/models")
async def create_model(body: CreateModelRequest):
    """创建新模型。"""
    config = load_models()

    # 检查 ID 是否已存在
    for model in config.get("models", []):
        if model.get("id") == body.id:
            return {"success": False, "error": f"模型 ID '{body.id}' 已存在"}

    new_model = {
        "id": body.id,
        "name": body.name,
        "api_key": body.api_key,
        "api_base": body.api_base,
        "temperature": body.temperature,
        "is_active": False,
    }
    config["models"].append(new_model)
    save_models(config)

    return {"success": True, "model": new_model}


@app.put(f"{API_PREFIX}/models/{{model_id}}")
async def update_model(model_id: str, body: UpdateModelRequest):
    """更新模型配置。"""
    config = load_models()

    # 查找模型
    target = None
    for model in config.get("models", []):
        if model.get("id") == model_id:
            target = model
            break

    if not target:
        return {"success": False, "error": "模型不存在"}

    # 更新字段
    if body.name is not None:
        target["name"] = body.name
    if body.api_key is not None:
        target["api_key"] = body.api_key
    if body.api_base is not None:
        target["api_base"] = body.api_base
    if body.temperature is not None:
        target["temperature"] = body.temperature

    save_models(config)
    return {"success": True, "model": target}


@app.delete(f"{API_PREFIX}/models/{{model_id}}")
async def delete_model(model_id: str):
    """删除模型。"""
    global _agent

    config = load_models()
    models = config.get("models", [])

    # 检查是否是最后一个模型
    if len(models) <= 1:
        return {"success": False, "error": "至少需要保留一个模型"}

    # 查找要删除的模型
    target = None
    for model in models:
        if model.get("id") == model_id:
            target = model
            break

    if not target:
        return {"success": False, "error": "模型不存在"}

    # 如果删除的是激活的模型，需要切换到另一个
    if target.get("is_active"):
        # 激活另一个模型
        for model in models:
            if model.get("id") != model_id and model.get("api_key"):
                set_active_model(model["id"])
                new_agent = _create_agent_with_model(model, _mcp_tools)
                with _agent_lock:
                    global _agent
                    _agent = new_agent
                break

    # 删除模型
    config["models"] = [m for m in models if m.get("id") != model_id]
    save_models(config)

    return {"success": True}


def _estimate_tokens(text: str) -> tuple[int, int]:
    """估算 token 数量和上下文使用率。

    Args:
        text: 文本内容

    Returns:
        (token_count, context_usage_percent)
    """
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    other_chars = len(text) - chinese_chars - english_chars
    estimated_tokens = int(chinese_chars * 2.5 + english_chars * 0.25 + other_chars * 0.5)
    context_usage = min(int((estimated_tokens / 200000) * 100), 100)
    return estimated_tokens, context_usage


@app.websocket(f"{API_PREFIX}/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token != CONFIG.get("ws_token", ""):
        await websocket.close(code=4001, reason="未授权")
        return

    await websocket.accept()

    # 维护对话历史
    conversation_history: list[dict] = []

    try:
        while True:
            data = await websocket.receive_json()
            user_content = data.get("content", "")

            if not user_content:
                continue

            # 添加用户消息到历史
            conversation_history.append({"role": "user", "content": user_content})

            full_response = ""

            try:
                with _agent_lock:
                    agent = _agent
                async for chunk in agent.astream(
                    {"messages": conversation_history},
                    stream_mode="updates"
                ):
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
                        await websocket.send_json({
                            "type": "thinking",
                            "content": f"[调用工具] {tool_name}",
                        })

                    elif "tool_result" in chunk:
                        result = chunk.get("tool_result", "")
                        await websocket.send_json({
                            "type": "thinking",
                            "content": f"[工具返回] {str(result)[:100]}...",
                        })

                normalized = full_response.replace('<think>', '<thinking>').replace('</think>', '</thinking>')

                estimated_tokens, context_usage = _estimate_tokens(normalized)

                await websocket.send_json({
                    "type": "token_usage",
                    "content": "",
                    "token_count": estimated_tokens,
                    "context_usage": context_usage
                })

                thinking_parts = re.findall(r'<thinking>(.*?)</thinking>', normalized, flags=re.DOTALL)
                response_text = re.sub(r'<thinking>.*?</thinking>', '', normalized, flags=re.DOTALL).strip()
                thinking_text = '\n'.join(thinking_parts)

                if thinking_parts:
                    all_thinking = '\n'.join(part.strip() for part in thinking_parts)
                    await websocket.send_json({
                        "type": "thinking",
                        "content": all_thinking,
                    })

                if response_text:
                    chunk_size = 3
                    for i in range(0, len(response_text), chunk_size):
                        chunk = response_text[i:i+chunk_size]
                        await websocket.send_json({
                            "type": "chunk",
                            "content": chunk,
                        })

                    await websocket.send_json({
                        "type": "final",
                        "content": response_text,
                    })

                await websocket.send_json({
                    "type": "done",
                    "content": "",
                })

                # 将助手回复添加到历史
                if response_text:
                    conversation_history.append({"role": "assistant", "content": response_text})

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Agent error: {error_msg}")
                await websocket.send_json({
                    "type": "error",
                    "content": error_msg,
                })

    except WebSocketDisconnect:
        logger.info("客户端断开连接")


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


@app.get(f"{API_PREFIX}/channels")
async def get_channels():
    """获取所有通道状态"""
    from .channels import ChannelRegistry
    registry: ChannelRegistry = request.app.state.channel_registry
    channels = []
    for ch in registry.list_all():
        channels.append({
            "id": ch.id,
            "type": ch.type.value if hasattr(ch.type, "value") else str(ch.type),
            "status": ch.status.value if hasattr(ch.status, "value") else str(ch.status),
            "enabled": True,
        })
    return {"channels": channels}