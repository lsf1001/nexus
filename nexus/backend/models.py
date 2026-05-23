from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class WSMessage(BaseModel):
    """WebSocket 传入消息。"""
    session_id: Optional[str] = None
    content: str


class StreamEvent(BaseModel):
    """WebSocket 传出事件。"""
    type: str  # thinking, tool_call, tool_result, final, done
    content: str
    session_id: str


class Session(BaseModel):
    """会话模型。"""
    id: str
    title: Optional[str] = None
    show_thinking: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Message(BaseModel):
    """消息模型。"""
    id: str
    session_id: str
    role: str  # user / assistant
    content: str
    thinking_content: Optional[str] = None
    created_at: Optional[datetime] = None