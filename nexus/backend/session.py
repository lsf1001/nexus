import uuid
from datetime import datetime
from typing import Optional

import aiosqlite

from .database import DATABASE_PATH


async def create_session(title: str = None, show_thinking: bool = True) -> str:
    """创建新会话，返回 session_id。"""
    session_id = str(uuid.uuid4())
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO sessions (id, title, show_thinking) VALUES (?, ?, ?)",
            (session_id, title or "新对话", show_thinking)
        )
        await db.commit()
    return session_id


async def get_session(session_id: str) -> Optional[dict]:
    """根据 ID 获取会话。"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_message(session_id: str, role: str, content: str, thinking_content: str = None) -> str:
    """添加消息到会话，返回 message_id。"""
    message_id = str(uuid.uuid4())
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO messages (id, session_id, role, content, thinking_content) VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, thinking_content)
        )
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        await db.commit()
    return message_id


async def get_conversation_history(session_id: str) -> list[dict]:
    """获取对话历史，格式化为 DeepAgents 所需格式。"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]


async def get_session_settings(session_id: str) -> dict:
    """获取会话设置。"""
    session = await get_session(session_id)
    return {"show_thinking": session.get("show_thinking", True)} if session else {"show_thinking": True}