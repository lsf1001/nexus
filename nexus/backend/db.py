"""会话数据库管理。

使用 SQLite 存储会话、消息。长期记忆已迁出至
``~/.nexus/AGENTS.md``(由 deepagents ``MemoryMiddleware`` 自动加载),
旧 ``memory`` 表迁移后改名为 ``memory_legacy``(只读,供回查)。
"""

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

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
def get_db() -> Iterator[sqlite3.Connection]:
    """获取 SQLite 连接的上下文管理器,首次访问时自动建表。

    启用 PRAGMA:
      - ``foreign_keys=ON`` (默认关闭)
      - ``journal_mode=WAL`` (并发读优化)
      - ``synchronous=NORMAL`` (WAL 模式下 fsync 折中)
      - ``busy_timeout=30000ms`` (抗 aiosqlite 写锁等待)

    Yields:
        已配置 row_factory 的 :class:`sqlite3.Connection`,调用方在
        ``with`` 块退出时会自动 commit,异常时回滚 + 关闭。
    """
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
        try:
            _create_tables(conn)
            _INITED = True
        except Exception:
            # _create_tables 失败时回滚 flag,允许同进程重试
            # (lifespan 重启 / 测试 setup 重入 / 启动期 transient 故障)。
            # rollback 清理已开事务里可能残留的 DDL,finally 仍会 close。
            conn.rollback()
            raise
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

    # Plan 5 (2026-07-12):wechat 索引化 — sessions 表加 account_id /
    # wechat_user_id / channel_meta 列,把 user_id → session_id 映射从
    # messages.content LIKE 检索迁到正经列(性能 100k 行 100-500ms → < 5ms)。
    # channel_meta 是 JSON TEXT,留给未来 feishu / telegram 通道的元数据扩展。
    _ensure_column(conn, "sessions", "account_id", "TEXT")
    _ensure_column(conn, "sessions", "wechat_user_id", "TEXT")
    _ensure_column(conn, "sessions", "channel_meta", "TEXT")

    # partial index:WHERE deleted_at IS NULL 把软删行排除在外,索引体积更小,
    # 查询计划走更窄的范围。wechat_user_id 索引额外过滤 IS NOT NULL,
    # 因为 main channel 的 wechat_user_id 是 NULL,索引它们没意义。
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_channel_account "
        "ON sessions(channel, account_id, updated_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_wechat_user "
        "ON sessions(wechat_user_id) "
        "WHERE deleted_at IS NULL AND wechat_user_id IS NOT NULL"
    )

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

    # Task 11:fact-check pipeline 在 quality_scores 上加 4 列。
    # claims/results 是 JSON 数组(经 json.dumps 序列化为 TEXT 存储);status 是 pass/repair/reject
    # 文本标签;latency_ms 是整型毫秒数。均为可空,保证旧调用模式不受影响。
    _ensure_column(conn, "quality_scores", "fact_check_claims", "TEXT")
    _ensure_column(conn, "quality_scores", "fact_check_results", "TEXT")
    _ensure_column(conn, "quality_scores", "fact_check_status", "TEXT")
    _ensure_column(conn, "quality_scores", "fact_check_latency_ms", "INTEGER")

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
    fact_check_claims: list[dict[str, Any]] | None = None,
    fact_check_results: list[dict[str, Any]] | None = None,
    fact_check_status: str | None = None,
    fact_check_latency_ms: int | None = None,
) -> int:
    """写入一条质量评分记录到 ``quality_scores`` 表（Phase 2 Task 2.5）。

    Args:
        session_id: 所属会话 ID。
        rubric: Rubric 名（如 ``"faithfulness"``），单维度写入。
        score: 该维度的 0.0-1.0 评分。
        verdict: 综合判定（``"accept"`` / ``"repair"`` / ``"reject"``）。
        reasoning: 评分员解释（中文），可空。
        message_id: 关联的 assistant 消息 ID，可空。
        fact_check_claims: Task 11 新增。fact-check pipeline 抽取的事实声明列表
            （每项 dict），None 表示未跑 fact-check；非 None 时会被 ``json.dumps``
            序列化为 TEXT 存储。
        fact_check_results: Task 11 新增。逐条声明的验证结果（每项 dict，含
            ``status`` / ``confidence`` 等字段），同样 ``json.dumps`` 序列化。
        fact_check_status: Task 11 新增。fact-check 综合判定（``"pass"`` /
            ``"partial"`` / ``"fail"`` 等），TEXT 类型，可空。
        fact_check_latency_ms: Task 11 新增。fact-check 阶段耗时（毫秒），可空。

    Returns:
        新插入行的 ``id``。
    """
    # JSON 列用 json.dumps 序列化为 TEXT；None 保留 NULL,保持向后兼容
    claims_json = json.dumps(fact_check_claims, ensure_ascii=False) if fact_check_claims is not None else None
    results_json = json.dumps(fact_check_results, ensure_ascii=False) if fact_check_results is not None else None

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO quality_scores
                (session_id, message_id, rubric, score, verdict, reasoning,
                 fact_check_claims, fact_check_results, fact_check_status, fact_check_latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                message_id,
                rubric,
                score,
                verdict,
                reasoning,
                claims_json,
                results_json,
                fact_check_status,
                fact_check_latency_ms,
            ),
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


def create_session(
    session_id: str,
    title: str | None = None,
    channel: str = "main",
    account_id: str | None = None,
    wechat_user_id: str | None = None,
    channel_meta: dict[str, Any] | None = None,
) -> dict:
    """创建新会话(idempotent — 已存在则复用,避免 FK constraint)。

    关键:客户端在 WS 首条消息 body 传 ``session_id``(用于多轮 / 续传)时,
    服务端不能假设该 id 已存在于 sessions 表。早期实现用 ``INSERT`` 不带
    OR IGNORE,直接覆盖客户端的 id 而不查存在性,后续 ``add_message`` 写
    messages(session_id FK → sessions.id)会触发 FOREIGN KEY constraint
    failed,WS 连接异常断开。

    现改为 ``INSERT OR IGNORE``:已存在则不写,再 SELECT 拿回真实行
    (title / channel / account_id / wechat_user_id 保留原值,新传入的
    这些参数仅在新行生效)。

    Plan 5 (2026-07-12):加 ``account_id`` / ``wechat_user_id`` / ``channel_meta``
    三个可选参。channel_meta 是 dict(用 json.dumps 序列化为 TEXT 存储),
    留给未来 feishu / telegram 通道的元数据扩展;旧调用方不传则保持原行为
    (None → NULL)。

    Returns:
        实际写入或已存在的 sessions 行 dict。
    """
    now = datetime.now().isoformat()
    channel_meta_json = json.dumps(channel_meta, ensure_ascii=False) if channel_meta is not None else None
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions "
            "(id, title, created_at, updated_at, channel, account_id, wechat_user_id, channel_meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, title, now, now, channel, account_id, wechat_user_id, channel_meta_json),
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
                "account_id": account_id,
                "wechat_user_id": wechat_user_id,
                "channel_meta": channel_meta,
            }
        return dict(row)


def get_session(session_id: str) -> dict | None:
    """获取会话。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row:
            return dict(row)
        return None


def _escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符 (\\ % _)。

    用于将任意字符串安全嵌入 LIKE 模式:``f"%{_escape_like(user_id)}%"``。
    使用反斜杠作为转义字符,通过 SQLite ``ESCAPE '\\\\'`` 子句激活。
    顺序很重要:必须先转义反斜杠自身,再转义 % 和 _。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_latest_session_by_user(
    user_id: str,
    channel: str = "wechat",
    account_id: str | None = None,
) -> str | None:
    """查找该 user_id 在指定 channel 上最近活跃的 session_id。

    用于：后端重启后，从 DB 重建"微信 user_id → session_id"映射，
    避免每次重启都给同一微信用户建一个新 session 导致历史断流。

    Plan 5 (2026-07-12):改为正经列查询 ``sessions.wechat_user_id`` +
    ``sessions.account_id``,不再 ``messages.content LIKE`` 扫消息表。
    旧实现有 2 个问题:(1)user_id 实际上不在 ``messages.content`` 里(只是
    会话级别元信息),LIKE 永远返回空 / 错命中;(2)没索引,100k 行全表
    扫描 100-500ms。新实现命中 ``idx_sessions_wechat_user`` partial
    index,< 5ms。
    """
    with get_db() as conn:
        if account_id is None:
            row = conn.execute(
                """
                SELECT id
                  FROM sessions
                 WHERE wechat_user_id = ?
                   AND channel = ?
                   AND deleted_at IS NULL
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                (user_id, channel),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id
                  FROM sessions
                 WHERE wechat_user_id = ?
                   AND account_id = ?
                   AND channel = ?
                   AND deleted_at IS NULL
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                (user_id, account_id, channel),
            ).fetchone()
        return row["id"] if row else None


def list_sessions(limit: int = 50) -> list[dict]:
    """列出所有未删除会话，按更新时间倒序。

    微信会话按 account_id 分组，每组只返回最新一个。
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at, deleted_at, channel,
                   account_id, wechat_user_id, channel_meta
              FROM (
                  SELECT s.*,
                         ROW_NUMBER() OVER (
                             PARTITION BY CASE WHEN s.channel = 'wechat'
                                                THEN COALESCE(s.account_id, '')
                                                ELSE s.id END
                             ORDER BY s.updated_at DESC
                         ) AS rn
                    FROM sessions s
                   WHERE s.deleted_at IS NULL
              )
             WHERE channel != 'wechat' OR rn = 1
             ORDER BY updated_at DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]  # ``rn`` 仅作过滤,不返回给调用方


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
