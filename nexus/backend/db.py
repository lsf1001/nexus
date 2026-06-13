"""会话数据库管理。

使用 SQLite 存储会话、消息和记忆。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import CONFIG

# 数据库路径
DB_PATH = Path.home() / ".nexus" / "nexus.db"

# 是否已执行过表初始化(进程内单次)
_INITED = False


def _get_db_path() -> Path:
    """获取数据库路径，确保目录存在。"""
    db_path = Path(CONFIG.get("db_path") or CONFIG.get("database_url") or str(DB_PATH))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@contextmanager
def get_db():
    """获取数据库连接的上下文管理器。首次访问时自动建表。"""
    global _INITED
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    # 启用外键级联（SQLite 默认关闭）+ WAL 模式（提升并发读）+ 降低同步频率
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if not _INITED:
        _INITED = True
        _create_tables(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _create_tables(conn: sqlite3.Connection) -> None:
    """建表 + 索引 + 列迁移。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            channel TEXT DEFAULT 'main'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_deleted_at ON sessions(deleted_at)")

    _ensure_column(conn, "sessions", "channel", "TEXT DEFAULT 'main'")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            thinking_content TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)")

    _ensure_column(conn, "messages", "thinking_content", "TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL CHECK (memory_type IN ('explicit', 'evolved', 'session')),
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(memory_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_category ON memory(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_key ON memory(key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory(updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_active ON memory(is_active)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_stats (
            tool_name TEXT PRIMARY KEY,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            total_latency REAL DEFAULT 0,
            last_used TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_stats (
            session_id TEXT PRIMARY KEY,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            success_outcomes INTEGER DEFAULT 0,
            failure_outcomes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            ended_at TEXT
        )
    """)

    # Phase 1 容错:质量评分表(rubric LLM 对回复打分,用于 accept/repair/reject)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quality_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message_id TEXT,
            rubric TEXT NOT NULL,
            score REAL NOT NULL,
            verdict TEXT NOT NULL,
            reasoning TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_session ON quality_scores(session_id)")

    # Phase 1 容错:断线续传 token 表(对应 resume.py 的 HMAC token)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resume_tokens (
            token TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            last_event_id INTEGER NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resume_tokens_session ON resume_tokens(session_id)")


def init_db() -> None:
    """显式初始化数据库表。get_db() 已自动调用,此函数主要给 CLI/启动入口使用。"""
    global _INITED
    with get_db() as conn:
        _create_tables(conn)
    _INITED = True
    _migrate_deleted_at()


def save_quality_score(
    session_id: str,
    rubric: str,
    score: float,
    verdict: str,
    reasoning: str = "",
    message_id: str | None = None,
) -> int:
    """写入一条质量评分记录到 ``quality_scores`` 表（Phase 2 Task 2.5）。

    Args:
        session_id: 所属会话 ID。
        rubric: Rubric 名（如 ``"faithfulness"``），单维度写入。
        score: 该维度的 0.0-1.0 评分。
        verdict: 综合判定（``"accept"`` / ``"repair"`` / ``"reject"``）。
        reasoning: 评分员解释（中文），可空。
        message_id: 关联的 assistant 消息 ID，可空。

    Returns:
        新插入行的 ``id``。
    """
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO quality_scores
                (session_id, message_id, rubric, score, verdict, reasoning)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, message_id, rubric, score, verdict, reasoning),
        )
        return int(cur.lastrowid or 0)


def _migrate_deleted_at() -> None:
    """迁移 deleted_at 索引。"""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='_migrate_deleted_at_idx'"
            )
            if cursor.fetchone():
                conn.execute("DROP INDEX _migrate_deleted_at_idx")
    except Exception:
        pass


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """确保表中存在指定列，若不存在则 ALTER TABLE 添加。

    使用 PRAGMA table_info 显式判断，避免 try/except 静默吞错。
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}  # row[1] = name
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ============================================================================
# 会话管理
# ============================================================================


def create_session(session_id: str, title: str | None = None, channel: str = "main") -> dict:
    """创建新会话。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, channel) VALUES (?, ?, ?, ?, ?)",
            (session_id, title, now, now, channel),
        )
        # 初始化会话统计
        conn.execute("INSERT INTO session_stats (session_id, created_at) VALUES (?, ?)", (session_id, now))
        return {
            "id": session_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "channel": channel,
        }


def get_session(session_id: str) -> dict | None:
    """获取会话。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row:
            return dict(row)
        return None


def find_latest_session_by_user(user_id: str, channel: str = "wechat") -> str | None:
    """查找该 user_id 在指定 channel 上最近活跃的 session_id。

    用于：后端重启后，从 DB 重建"微信 user_id → session_id"映射，
    避免每次重启都给同一微信用户建一个新 session 导致历史断流。
    """
    with get_db() as conn:
        # 通过 messages 表按 created_at 倒序找该 user_id 最近一条消息所属 session
        row = conn.execute(
            """
            SELECT s.id
              FROM messages m
              JOIN sessions s ON m.session_id = s.id
             WHERE s.channel = ?
               AND s.deleted_at IS NULL
               AND m.content LIKE ?
             ORDER BY m.created_at DESC
             LIMIT 1
            """,
            (channel, f"%{user_id}%"),
        ).fetchone()
        return row["id"] if row else None


def list_sessions(limit: int = 50) -> list[dict]:
    """列出所有未删除会话，按更新时间倒序。

    微信会话按 account_id 分组，每组只返回最新一个。
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM sessions WHERE deleted_at IS NULL ORDER BY updated_at DESC", ()).fetchall()

    sessions = [dict(row) for row in rows]

    # 微信会话按账户分组，每组只保留最新一个
    wechat_sessions_by_account: dict[str, dict] = {}
    main_sessions: list[dict] = []

    for s in sessions:
        if s.get("channel") == "wechat":
            # 从标题提取 account_id（格式：微信 {account_id[:8]} {user_id[:8]}）
            title = s.get("title", "")
            parts = title.split()
            if len(parts) >= 2:
                acc_id = parts[1]
            else:
                acc_id = "unknown"
            # 只保留每个账户的最新会话
            if acc_id not in wechat_sessions_by_account:
                wechat_sessions_by_account[acc_id] = s
        else:
            main_sessions.append(s)

    # 合并结果
    result = main_sessions + list(wechat_sessions_by_account.values())
    return result[:limit]


def list_deleted_sessions(limit: int = 50) -> list[dict]:
    """列出所有已删除会话，用于恢复。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def update_session(session_id: str, title: str | None = None) -> dict | None:
    """更新会话标题和更新时间。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        if title is not None:
            conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?", (title, now, session_id))
        else:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return get_session(session_id)


def delete_session(session_id: str) -> bool:
    """软删除会话（标记为已删除）。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE sessions SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now, session_id)
        )
        return cursor.rowcount > 0


def restore_session(session_id: str) -> bool:
    """恢复已删除的会话。"""
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE sessions SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL", (session_id,)
        )
        return cursor.rowcount > 0


def permanent_delete_session(session_id: str) -> bool:
    """永久删除会话及其所有消息。"""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0


def purge_old_sessions(days: int = 30) -> int:
    """清理指定天数前的已删除会话。返回删除数量。"""
    from datetime import timedelta

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))
        return cursor.rowcount


# ============================================================================
# 消息管理
# ============================================================================


def add_message(message_id: str, session_id: str, role: str, content: str, thinking_content: str | None = None) -> dict:
    """添加消息到会话。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages (id, session_id, role, content, thinking_content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message_id, session_id, role, content, thinking_content, now),
        )
        # 更新会话的更新时间
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        # 更新会话统计
        conn.execute("UPDATE session_stats SET message_count = message_count + 1 WHERE session_id = ?", (session_id,))
        return {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking_content": thinking_content,
            "created_at": now,
        }


def get_messages(session_id: str) -> list[dict]:
    """获取会话的所有消息。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_conversation_history(session_id: str) -> list[dict]:
    """获取会话的历史消息，用于 AI 对话。"""
    messages = get_messages(session_id)
    return [{"role": msg["role"], "content": msg["content"]} for msg in messages]


# ============================================================================
# 记忆管理
# ============================================================================


def save_memory(
    memory_id: str,
    memory_type: str,
    category: str,
    key: str,
    value: str,
    metadata: dict | None = None,
    expires_at: str | None = None,
) -> dict:
    """保存记忆。

    Args:
        memory_id: 记忆 ID
        memory_type: 记忆类型 ('explicit', 'evolved', 'session')
        category: 分类
        key: 记忆键
        value: 记忆值
        metadata: 元数据
        expires_at: 过期时间
    """
    now = datetime.now().isoformat()

    # 处理 key 冲突（同类型同 key 的旧记忆软删除）
    with get_db() as conn:
        conn.execute(
            "UPDATE memory SET is_active = 0 WHERE memory_type = ? AND key = ? AND is_active = 1", (memory_type, key)
        )

        conn.execute(
            """INSERT INTO memory (id, memory_type, category, key, value, metadata, created_at, updated_at, expires_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                memory_id,
                memory_type,
                category,
                key,
                value,
                json.dumps(metadata) if metadata else None,
                now,
                now,
                expires_at,
            ),
        )

        return {
            "id": memory_id,
            "memory_type": memory_type,
            "category": category,
            "key": key,
            "value": value,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now,
        }


def get_memory(
    session_id: str | None = None,
    memory_type: str | None = None,
    category: str | None = None,
    key: str | None = None,
    include_inactive: bool = False,
) -> list[dict]:
    """获取记忆列表。

    Args:
        session_id: 会话 ID（用于 session 类型记忆）
        memory_type: 记忆类型过滤
        category: 分类过滤
        key: 记忆键精确匹配
        include_inactive: 是否包含已删除的
    """
    conditions = ["is_active = 1"]
    params = []

    if memory_type:
        conditions.append("memory_type = ?")
        params.append(memory_type)

    if category:
        conditions.append("category = ?")
        params.append(category)

    if key:
        conditions.append("key = ?")
        params.append(key)

    if session_id and memory_type == "session":
        # session 类型记忆需要关联会话
        conditions.append("""
            id IN (SELECT id FROM memory WHERE memory_type = 'session' AND key = ?)
        """)
        params.append(session_id)

    where = " AND ".join(conditions) if conditions else "1=1"

    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM memory WHERE {where} ORDER BY updated_at DESC", params).fetchall()
        return [dict(row) for row in rows]


def search_memory(keyword: str, memory_type: str | None = None, limit: int = 10) -> list[dict]:
    """搜索记忆（全文搜索）。

    Args:
        keyword: 搜索关键词
        memory_type: 记忆类型过滤
        limit: 返回数量限制
    """
    conditions = ["is_active = 1"]
    params = []

    if keyword:
        conditions.append("(key LIKE ? OR value LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    if memory_type:
        conditions.append("memory_type = ?")
        params.append(memory_type)

    where = " AND ".join(conditions) if conditions else "1=1"

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM memory WHERE {where} ORDER BY updated_at DESC LIMIT ?", params + [limit]
        ).fetchall()
        return [dict(row) for row in rows]


def delete_memory(memory_id: str, hard: bool = False) -> bool:
    """删除记忆。

    Args:
        memory_id: 记忆 ID
        hard: 是否硬删除
    """
    with get_db() as conn:
        if hard:
            cursor = conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
        else:
            cursor = conn.execute("UPDATE memory SET is_active = 0 WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0


def list_user_memory(category: str | None = None, memory_types: list | None = None) -> list[dict]:
    """列出所有记忆。

    Args:
        category: 分类过滤
        memory_types: 记忆类型列表
    """
    conditions = ["is_active = 1"]
    params = []

    # 排除 session 类型（需要 session_id）
    conditions.append("(memory_type = 'explicit' OR memory_type = 'evolved')")

    if category:
        conditions.append("category = ?")
        params.append(category)

    if memory_types:
        placeholders = ",".join(["?" for _ in memory_types])
        conditions.append(f"memory_type IN ({placeholders})")
        params.extend(memory_types)

    where = " AND ".join(conditions)

    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM memory WHERE {where} ORDER BY updated_at DESC", params).fetchall()
        return [dict(row) for row in rows]


def get_session_memory(session_id: str, category: str | None = None) -> list[dict]:
    """获取会话的所有记忆。"""
    conditions = ["is_active = 1", "memory_type = 'session'", "key LIKE ?"]
    params = [f"{session_id}:%"]

    if category:
        conditions.append("category = ?")
        params.append(category)

    where = " AND ".join(conditions)

    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM memory WHERE {where} ORDER BY created_at DESC", params).fetchall()
        return [dict(row) for row in rows]


# ============================================================================
# 工具统计
# ============================================================================


def update_tool_stats(tool_name: str, success: bool, latency: float) -> None:
    """更新工具统计。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        if success:
            conn.execute(
                """INSERT INTO tool_stats (tool_name, success_count, total_latency, last_used)
                   VALUES (?, 1, ?, ?) ON CONFLICT(tool_name) DO UPDATE SET
                   success_count = success_count + 1,
                   total_latency = total_latency + ?,
                   last_used = ?""",
                (tool_name, latency, now, latency, now),
            )
        else:
            conn.execute(
                """INSERT INTO tool_stats (tool_name, failure_count, last_used)
                   VALUES (?, 1, ?) ON CONFLICT(tool_name) DO UPDATE SET
                   failure_count = failure_count + 1,
                   last_used = ?""",
                (tool_name, now, now),
            )


def get_tool_stats(tool_name: str) -> dict | None:
    """获取工具统计。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tool_stats WHERE tool_name = ?", (tool_name,)).fetchone()
        return dict(row) if row else None


def get_all_tool_stats() -> list[dict]:
    """获取所有工具统计。"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tool_stats ORDER BY last_used DESC").fetchall()
        return [dict(row) for row in rows]


# ============================================================================
# 会话统计
# ============================================================================


def update_session_stats(
    session_id: str,
    message_count: int | None = None,
    tool_call_count: int | None = None,
    success_outcomes: int | None = None,
    failure_outcomes: int | None = None,
) -> None:
    """更新会话统计。"""
    with get_db() as conn:
        updates = []
        params = []

        if message_count is not None:
            updates.append("message_count = ?")
            params.append(message_count)
        if tool_call_count is not None:
            updates.append("tool_call_count = ?")
            params.append(tool_call_count)
        if success_outcomes is not None:
            updates.append("success_outcomes = ?")
            params.append(success_outcomes)
        if failure_outcomes is not None:
            updates.append("failure_outcomes = ?")
            params.append(failure_outcomes)

        if updates:
            params.append(session_id)
            conn.execute(f"UPDATE session_stats SET {', '.join(updates)} WHERE session_id = ?", params)


def get_session_stats(session_id: str) -> dict | None:
    """获取会话统计。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM session_stats WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def end_session(session_id: str) -> None:
    """结束会话。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute("UPDATE session_stats SET ended_at = ? WHERE session_id = ?", (now, session_id))


# ============================================================================
# 清理任务
# ============================================================================


def cleanup_expired_memory() -> int:
    """清理过期记忆。返回删除数量。"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM memory WHERE expires_at IS NOT NULL AND expires_at < ? AND is_active = 1", (now,)
        )
        return cursor.rowcount


def cleanup_low_confidence_memory(threshold: float = 0.3) -> int:
    """清理低置信度知识。返回更新数量。"""
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE memory SET is_active = 0 WHERE memory_type = 'evolved' AND is_active = 1 AND JSON_EXTRACT(metadata, '$.confidence') < ?",
            (threshold,),
        )
        return cursor.rowcount


def cleanup_low_access_memory(days: int = 90) -> int:
    """清理低访问记忆。返回删除数量。"""
    from datetime import timedelta

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM memory WHERE memory_type = 'evolved' AND is_active = 1 AND updated_at < ?", (cutoff,)
        )
        return cursor.rowcount
