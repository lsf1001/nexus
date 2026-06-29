"""模型配置路由：CRUD + 切换激活模型。"""

from __future__ import annotations

import asyncio
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..api.ws import require_token
from ..models_config import load_models, save_models, set_active_model

router = APIRouter(prefix="/api/models", tags=["models"], dependencies=[Depends(require_token)])

# 这些全局对象由 main.py 注入（见 init_router）
_agent_lock: Lock | None = None
_mcp_tools: list = []
_create_agent_with_model = None
_set_global_agent = None
_rebuild_intent_and_quality = None


def init_router(
    agent_lock: Lock,
    mcp_tools: list,
    create_agent_with_model,
    set_global_agent,
    rebuild_intent_and_quality=None,
) -> None:
    """由 main.py 在启动时注入共享依赖。"""
    global _agent_lock, _mcp_tools, _create_agent_with_model, _set_global_agent, _rebuild_intent_and_quality
    _agent_lock = agent_lock
    _mcp_tools = mcp_tools
    _create_agent_with_model = create_agent_with_model
    _set_global_agent = set_global_agent
    _rebuild_intent_and_quality = rebuild_intent_and_quality


class SwitchModelRequest(BaseModel):
    """切换模型请求。"""

    id: str = Field(..., min_length=1, description="目标模型 ID")


class SwitchModelResponse(BaseModel):
    """切换模型响应。"""

    success: bool
    active_model: dict | None = None
    error: str | None = None


class CreateModelRequest(BaseModel):
    """创建模型请求。"""

    id: str = Field(..., min_length=1, description="模型ID")
    name: str = Field(default="New Model", description="模型名称")
    api_key: str = Field(default="", description="API密钥")
    api_base: str = Field(default="https://api.minimaxi.com/v1", description="API端点")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")


class UpdateModelRequest(BaseModel):
    """更新模型请求。"""

    name: str | None = Field(default=None, description="模型名称")
    api_key: str | None = Field(default=None, description="API密钥")
    api_base: str | None = Field(default=None, description="API端点")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="温度参数")


class DefaultModelRequest(BaseModel):
    """首启配置 / 默认模型请求。"""

    name: str = Field(..., min_length=1, description="模型名称")
    api_key: str = Field(..., min_length=1, description="API密钥")
    api_base: str = Field(..., min_length=1, description="API端点")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")


@router.put("/default")
async def set_default_model(body: DefaultModelRequest) -> dict:
    """首启配置入口：写入激活模型并立即重置 Agent。

    语义：把当前 active 模型（或第一个模型）替换为请求体内容并激活。
    写入后调用 ``_create_agent_with_model`` 重建 Agent，避免用户必须重启。
    """
    config = load_models()
    models = config.get("models") or []

    target = None
    for model in models:
        if model.get("is_active"):
            target = model
            break
    if target is None and models:
        target = models[0]

    if target is None:
        # 没有任何模型：创建第一个
        new_model = {
            "id": "default",
            "name": body.name,
            "api_key": body.api_key,
            "api_base": body.api_base,
            "temperature": body.temperature,
            "is_active": True,
        }
        config["models"] = [new_model]
        target = new_model
    else:
        target["name"] = body.name
        target["api_key"] = body.api_key
        target["api_base"] = body.api_base
        target["temperature"] = body.temperature
        target["is_active"] = True
        # 互斥：其它模型标为 inactive
        for m in models:
            if m is not target:
                m["is_active"] = False

    save_models(config)

    # 立即重建 Agent，让首次配置后立刻可用
    # WHY run_in_executor:同 ``switch_model`` — 在 uvicorn event loop 内调 sync
    # ``_create_agent_with_model`` 会让 ``_create_checkpointer`` 的 ``asyncio.run``
    # 炸 RuntimeError。推到 ``ThreadPoolExecutor`` 后台线程,无 loop,正常跑。
    if _create_agent_with_model is not None:
        new_agent = await asyncio.get_running_loop().run_in_executor(None, _create_agent_with_model, target, _mcp_tools)
        if new_agent is not None and _set_global_agent is not None:
            _set_global_agent(new_agent)
        if _rebuild_intent_and_quality is not None:
            await asyncio.get_running_loop().run_in_executor(None, _rebuild_intent_and_quality, None)

    return {"success": True, "model": target}


@router.get("")
async def get_models():
    """获取所有模型列表。"""
    config = load_models()
    # 出于安全：列表接口不返回真实 api_key，只返回是否已配置。
    masked = []
    for m in config.get("models", []):
        item = dict(m)
        if item.get("api_key"):
            item["api_key"] = "***" + item["api_key"][-4:] if len(item["api_key"]) > 4 else "***"
        else:
            item["api_key"] = ""
        masked.append(item)
    return masked


@router.post("/switch", response_model=SwitchModelResponse)
async def switch_model(body: SwitchModelRequest):
    """切换当前激活的模型。"""
    model_id = body.id

    config = load_models()
    target = None
    for model in config.get("models", []):
        if model.get("id") == model_id:
            target = model
            break

    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")

    api_key = target.get("api_key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 {target.get('name')} 未配置 API Key，无法使用",
        )

    set_active_model(model_id)

    # WHY run_in_executor:``_create_agent_with_model`` 内部调 ``create_agent``
    # → ``_create_checkpointer`` → ``_asyncio.run(_build_async_saver())``。
    # 这条 sync 路径在 uvicorn worker 线程的**已运行** event loop 里会抛
    # ``RuntimeError: asyncio.run() cannot be called from a running event loop``。
    # ``loop.run_in_executor`` 把同步初始化推到 ``ThreadPoolExecutor`` 的后台线程,
    # 那里无 loop,``asyncio.run`` 正常工作。当前 HTTP 端点 await 期间释放回 uvicorn,
    # 不阻塞事件循环。E2E 2026-06-27 ``test_e2e_04_models_crud`` 暴露这个 500。
    new_agent = await asyncio.get_running_loop().run_in_executor(None, _create_agent_with_model, target, _mcp_tools)
    if new_agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 {target.get('name')} 配置无效，无法使用",
        )

    _set_global_agent(new_agent)
    if _rebuild_intent_and_quality is not None:
        await asyncio.get_running_loop().run_in_executor(None, _rebuild_intent_and_quality, None)
    return SwitchModelResponse(
        success=True,
        active_model={"id": target.get("id"), "name": target.get("name")},
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_model(body: CreateModelRequest):
    """创建新模型。"""
    config = load_models()

    for model in config.get("models", []):
        if model.get("id") == body.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"模型 ID '{body.id}' 已存在",
            )

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


@router.put("/{model_id}")
async def update_model(model_id: str, body: UpdateModelRequest):
    """更新模型配置。"""
    config = load_models()

    target = None
    for model in config.get("models", []):
        if model.get("id") == model_id:
            target = model
            break

    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")

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


@router.delete("/{model_id}")
async def delete_model(model_id: str):
    """删除模型。"""
    config = load_models()
    models = config.get("models", [])

    if len(models) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要保留一个模型",
        )

    target = None
    for model in models:
        if model.get("id") == model_id:
            target = model
            break

    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型不存在")

    if target.get("is_active"):
        # 在删 active 之前先把 fallback 选好并落盘。如果没有任何剩余 model 有
        # 可用 api_key，则不能继续把全局 _agent 指向要删的 model。
        fallback = None
        for model in models:
            if model.get("id") != model_id and model.get("api_key"):
                fallback = model
                break
        if fallback is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无法删除当前激活模型：没有其它已配置 API Key 的模型可切换",
            )
        set_active_model(fallback["id"])
        # WHY run_in_executor:同 ``switch_model`` / ``set_default_model`` — 在
        # uvicorn event loop 内调 sync ``_create_agent_with_model`` 会让
        # ``_create_checkpointer`` 的 ``asyncio.run`` 炸 RuntimeError。
        new_agent = await asyncio.get_running_loop().run_in_executor(
            None, _create_agent_with_model, fallback, _mcp_tools
        )
        if new_agent is None:
            # 极端情况：fallback 看起来有 key 但 _create_agent_with_model 拒绝
            # （如 model name 非法）。不要把全局 _agent 清成 None。
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法切换到备用模型 {fallback.get('name')}：构造 Agent 失败",
            )
        _set_global_agent(new_agent)
        if _rebuild_intent_and_quality is not None:
            await asyncio.get_running_loop().run_in_executor(None, _rebuild_intent_and_quality, None)

    config["models"] = [m for m in models if m.get("id") != model_id]
    save_models(config)
    return {"success": True}
