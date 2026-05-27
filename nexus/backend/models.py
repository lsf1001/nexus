"""数据模型定义。

使用 Pydantic 提供类型安全和验证。
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class WSMessage(BaseModel):
    """WebSocket 传入消息。"""
    session_id: Optional[str] = None
    content: str = Field(..., min_length=1, description="消息内容")


class StreamEvent(BaseModel):
    """WebSocket 传出事件。"""
    type: str = Field(..., pattern="^(thinking|tool_call|tool_result|final|done)$", description="事件类型")
    content: str
    session_id: str


class Session(BaseModel):
    """会话模型。"""
    id: str = Field(..., min_length=1)
    title: Optional[str] = Field(default=None, max_length=100)
    show_thinking: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Message(BaseModel):
    """消息模型。"""
    id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    thinking_content: Optional[str] = None
    created_at: Optional[datetime] = None


class ModelConfig(BaseModel):
    """模型配置。"""
    id: str = Field(..., min_length=1, description="模型ID")
    name: str = Field(default="MiniMax-M2.7", description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    api_base: Optional[str] = Field(default=None, description="API端点")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    is_active: bool = False


class SwitchModelRequest(BaseModel):
    """切换模型请求。"""
    id: str = Field(..., min_length=1, description="目标模型ID")


class SwitchModelResponse(BaseModel):
    """切换模型响应。"""
    success: bool
    error: Optional[str] = None
    active_model: Optional[dict] = None


class TokenUsage(BaseModel):
    """Token 使用情况。"""
    type: str = "token_usage"
    token_count: int = Field(ge=0)
    context_usage: int = Field(ge=0, le=100, description="上下文使用百分比")