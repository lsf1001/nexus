"""share_tokens 表 DDL。

WHY 独立模块:``share_tokens`` 是 Round 3 (2026-08-05) 的会话分享 token 表,
其 CRUD 在 ``backend/share_store.py``,但 DDL 历史上一直挂在 ``db._create_tables``
里。拆出来是为了让 ``db/__init__.py`` 回到 800 行硬约束以内(CLAUDE.md §1.2)。

放这里而不是 ``share_store.py``:``share_store`` 已 ``from . import db``,
若把 DDL 放进去会形成 ``db → share_store → db`` 循环导入。

表语义:
  - ``resume_tokens`` 是 WS 续传 HMAC(短命,与 ws 帧挂钩),不能复用。
  - ``share_tokens`` 是 user 显式触发的"创建公开只读快照",7 天过期 + 可撤销。
  - FK ``session_id → sessions(id)`` **不带** ON DELETE CASCADE:业务上希望
    "原会话删了,share 链接还能看历史快照"。
"""

from __future__ import annotations

import sqlite3

_SHARE_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS share_tokens (
    token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_share_tokens_session
    ON share_tokens(session_id);
"""


def create_share_tokens_table(conn: sqlite3.Connection) -> None:
    """建 ``share_tokens`` 表 + 索引(幂等,``IF NOT EXISTS``)。"""
    conn.executescript(_SHARE_TOKENS_DDL)
