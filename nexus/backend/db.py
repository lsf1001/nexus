"""会话数据库管理。

使用 SQLite 存储会话、消息。长期记忆已迁出至
``~/.nexus/AGENTS.md``(由 deepagents ``MemoryMiddleware`` 自动加载),
旧 ``memory`` 表迁移后改名为 ``memory_legacy``(只读,供回查)。
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import CONFIG

logger = logging.getLogger(__name__)

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
    # 30s busy_timeout:agent.py 的 AsyncSqliteStore/AsyncSqliteSaver
    # (aiosqlite 后台线程) 与本连接同库同表,aiosqlite 持 WAL 写锁期间
    # sync 写会立即 OperationalError。30s 等待覆盖 agent 懒构造时
    # AsyncSqliteStore.setup() 的 DDL(实测在 5-15s 之间,busy_timeout=5000
    # 仍然不够)。30s 是 SQLite 默认上限,生产经验值能扛住 99% 场景。
    conn.execute("PRAGMA busy_timeout = 30000")
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
    _ensure_column(conn, "messages", "intent", "TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_legacy (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_legacy(memory_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_category ON memory_legacy(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_key ON memory_legacy(key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory_legacy(updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_active ON memory_legacy(is_active)")

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
    """迁移 deleted_at 索引 (幂等,失败仅警告)。"""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='_migrate_deleted_at_idx'"
            )
            if cursor.fetchone():
                conn.execute("DROP INDEX _migrate_deleted_at_idx")
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        # 索引迁移非业务关键路径,失败不致命,仅记录
        logger.warning("_migrate_deleted_at 失败 (非致命): %s", exc)


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
    """创建新会话(idempotent — 已存在则复用,避免 FK constraint)。

    关键:客户端在 WS 首条消息 body 传 ``session_id``(用于多轮 / 续传)时,
    服务端不能假设该 id 已存在于 sessions 表。早期实现用 ``INSERT`` 不带
    OR IGNORE,直接覆盖客户端的 id 而不查存在性,后续 ``add_message`` 写
    messages(session_id FK → sessions.id)会触发 FOREIGN KEY constraint
    failed,WS 连接异常断开。

    现改为 ``INSERT OR IGNORE``:已存在则不写,再 SELECT 拿回真实行
    (title / channel 保留原值,新传入的 title 仅在新行生效)。

    Returns:
        实际写入或已存在的 sessions 行 dict。
    """
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at, channel) VALUES (?, ?, ?, ?, ?)",
            (session_id, title, now, now, channel),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            # 极端情况:INSERT OR IGNORE 因 UNIQUE 冲突跳过,但 SELECT 拿不到
            # 行(理论上不应发生);回落到返回构造 dict
            return {
                "id": session_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "channel": channel,
            }
        return dict(row)


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
    """更新会话标题和更新时间。

    注意:返回最新行必须用**同一连接** SELECT,不能用 ``get_session``
    重新打开连接 —— ``get_db()`` 的 commit 在 ``with`` 退出时才执行,
    同一 ``with`` 块里嵌套 ``get_session`` 会读到 UPDATE 之前的旧数据
    (Bug #1,2026-06 E2E 矩阵发现)。
    """
    now = datetime.now().isoformat()
    with get_db() as conn:
        if title is not None:
            conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?", (title, now, session_id))
        else:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


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


def add_message(
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    thinking_content: str | None = None,
    intent: str | None = None,
) -> dict:
    """添加消息到会话。

    Args:
        message_id: 消息 ID。
        session_id: 所属会话 ID。
        role: 角色（user / assistant）。
        content: 消息正文。
        thinking_content: 思维链内容（可空）。
        intent: 意图分类标签（chitchat / knowledge / task / None）。
            旧调用方不传时，字段为 NULL，行为向后兼容。
    """
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages (id, session_id, role, content, thinking_content, intent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, session_id, role, content, thinking_content, intent, now),
        )
        # 更新会话的更新时间
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking_content": thinking_content,
            "intent": intent,
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
