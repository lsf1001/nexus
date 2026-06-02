"""模型配置路由：CRUD + 切换激活模型。"""
from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from threading import Lock

from ..models_config import load_models, save_models, set_active_model

router = APIRouter(prefix="/api/models", tags=["models"])

# 这些全局对象由 main.py 注入（见 init_router）
_agent_lock: Optional[Lock] = None
_mcp_tools: list = []
_create_agent_with_model = None
_set_global_agent = None


def init_router(agent_lock: Lock, mcp_tools: list, create_agent_with_model, set_global_agent) -> None:
    """由 main.py 在启动时注入共享依赖。"""
    global _agent_lock, _mcp_tools, _create_agent_with_model, _set_global_agent
    _agent_lock = agent_lock
    _mcp_tools = mcp_tools
    _create_agent_with_model = create_agent_with_model
    _set_global_agent = set_global_agent


class SwitchModelRequest(BaseModel):
    """切换模型请求。"""
    id: str = Field(..., min_length=1, description="目标模型 ID")


class SwitchModelResponse(BaseModel):
    """切换模型响应。"""
    success: bool
    active_model: Optional[dict] = None
    error: Optional[str] = None


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


@router.get("")
async def get_models():
    """获取所有模型列表。"""
    config = load_models()
    return config.get("models", [])


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

    new_agent = _create_agent_with_model(target, _mcp_tools)
    if new_agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"模型 {target.get('name')} 配置无效，无法使用",
        )

    _set_global_agent(new_agent)
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
        for model in models:
            if model.get("id") != model_id and model.get("api_key"):
                set_active_model(model["id"])
                new_agent = _create_agent_with_model(model, _mcp_tools)
                _set_global_agent(new_agent)
                break

    config["models"] = [m for m in models if m.get("id") != model_id]
    save_models(config)
    return {"success": True}
