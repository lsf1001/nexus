"""会话管理 API。"""

from __future__ import annotations

import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException

from .api.ws import require_token
from .db import (
    add_message,
    create_session,
    delete_session,
    get_conversation_history,
    get_messages,
    get_session,
    list_deleted_sessions,
    list_sessions,
    permanent_delete_session,
    purge_old_sessions,
    restore_session,
    update_session,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(require_token)])


# ============================================================================
# SessionManager - 统一会话管理
# ============================================================================


class SessionManager:
    """统一会话上下文管理。

    职责：
    - 管理会话生命周期
    - 构建带对话历史的 prompt（身份/记忆由 deepagents MemoryMiddleware 注入）
    - 提供流式响应接口
    """

    def __init__(self) -> None:
        """初始化会话管理器。"""

    def build_prompt(self, session_id: str, user_message: str) -> dict:
        """构建带对话历史的 prompt。

        身份 / 规则 / 长期记忆由 deepagents :class:`MemoryMiddleware` 从
        AGENTS.md 注入 system prompt;本方法只组装历史 + 当前 user 消息。

        Args:
            session_id: 会话 ID
            user_message: 用户消息

        Returns:
            包含 session_id、messages 的字典
        """
        from .db import get_conversation_history

        # 若最后一条就是当前 user 消息（调用方先入库再调本方法），去掉以免重复
        history = get_conversation_history(session_id)
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            history = history[:-1]

        # 组装消息：身份由 AGENTS.md 注入,这里 system 段留空
        messages: list[dict] = [{"role": "system", "content": ""}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        return {
            "session_id": session_id,
            "messages": messages,
        }


# 全局单例
_session_manager: SessionManager | None = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """获取会话管理器单例（线程安全）。"""
    global _session_manager
    if _session_manager is None:
        with _manager_lock:
            if _session_manager is None:
                _session_manager = SessionManager()
    return _session_manager


@router.get("")
async def get_sessions(limit: int = 50) -> list[dict]:
    """获取会话列表。"""
    return list_sessions(limit=limit)


@router.post("")
async def create_new_session(body: dict | None = None) -> dict:
    """创建新会话。"""
    session_id = str(uuid.uuid4())
    title = body.get("title") if body else None
    channel = body.get("channel", "main") if body else "main"
    return create_session(session_id, title=title, channel=channel)


@router.get("/deleted")
async def get_deleted_sessions(limit: int = 50) -> list[dict]:
    """获取已删除的会话列表（用于恢复）。"""
    return list_deleted_sessions(limit=limit)


@router.post("/purge")
async def purge_old_deleted_sessions(days: int = 30) -> dict:
    """清理指定天数前的已删除会话。"""
    count = purge_old_sessions(days)
    return {"success": True, "deleted_count": count, "message": f"已清理 {count} 个超过 {days} 天的会话"}


@router.get("/{session_id}")
async def get_session_detail(session_id: str) -> dict:
    """获取会话详情。"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = get_messages(session_id)
    return {**session, "messages": messages}


@router.put("/{session_id}")
async def update_session_title(session_id: str, title: str | None = None) -> dict:
    """更新会话标题。"""
    session = update_session(session_id, title=title)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.delete("/{session_id}")
async def delete_session_by_id(session_id: str) -> dict:
    """软删除会话（可恢复）。"""
    success = delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return {"success": True, "message": "会话已移到回收站"}


@router.post("/{session_id}/restore")
async def restore_session_by_id(session_id: str) -> dict:
    """恢复已删除的会话。"""
    success = restore_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在或未删除")
    return {"success": True, "message": "会话已恢复"}


@router.delete("/{session_id}/permanent")
async def permanent_delete_session_by_id(session_id: str) -> dict:
    """永久删除会话（不可恢复）。"""
    success = permanent_delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True, "message": "会话已永久删除"}


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str) -> list[dict]:
    """获取会话的所有消息。"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return get_messages(session_id)


@router.get("/{session_id}/history")
async def get_session_conversation_history(session_id: str) -> list[dict]:
    """获取会话的对话历史（用于 AI）。"""
    return get_conversation_history(session_id)


@router.post("/{session_id}/messages")
async def add_message_to_session(session_id: str, body: dict) -> dict:
    """添加消息到会话。"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    role = body.get("role")
    content = body.get("content")
    thinking_content = body.get("thinking_content")

    if not role or not content:
        raise HTTPException(status_code=400, detail="role 和 content 是必填字段")

    message_id = str(uuid.uuid4())
    return add_message(message_id, session_id, role, content, thinking_content)
