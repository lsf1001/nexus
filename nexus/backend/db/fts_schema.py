"""messages 表的 FTS5 全文搜索索引维护。

WHY 独立模块:建表 + tokenizer 迁移 + 老行 rebuild 三件事只服务
``messages_fts``,与 sessions / quality_scores 无关,混在 ``__init__.py``
里会把 db 包推到 800 行硬约束之上(CLAUDE.md §1.2)。

设计约束:
  - ``migrate_messages_fts_to_trigram`` 只做 schema(DROP + 重建前检查),
    由 ``db/__init__.py`` 的 ``_create_tables`` 调用。
  - ``rebuild_fts_once`` 需要一条已建表的连接,所以接收 ``conn`` 而不自己
    ``sqlite3.connect``(与 ``QualityScoreRepo`` 相同的注入约定)。
"""

from __future__ import annotations

import sqlite3


def migrate_messages_fts_to_trigram(conn: sqlite3.Connection) -> None:
    """旧 unicode61 tokenizer 的 messages_fts 重建为 trigram,支持中文搜索。

    WHY:Task 3.1(commit 88e1a25)默认 unicode61,中文 partial MATCH 0 命中;
    Task 3.2 改 trigram,但已存在的 FTS5 表不会自动升级 — 必须 DROP + CREATE。
    检测:sqlite_master 里 messages_fts 的 CREATE SQL 含 'tokenize='trigram'' 则 no-op。
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='messages_fts'").fetchone()
    if row is None:
        return
    sql = row[0] or ""
    if "tokenize='trigram'" in sql:
        return
    # 先 DROP 触发器:DROP TABLE 不会级联 DROP 依赖 triggers,留 dangling triggers
    # 会导致重建同名表时新 triggers DROP 失败,触发器路径坏。
    conn.execute("DROP TRIGGER IF EXISTS messages_ai")
    conn.execute("DROP TRIGGER IF EXISTS messages_ad")
    conn.execute("DROP TRIGGER IF EXISTS messages_au")
    conn.execute("DROP TABLE IF EXISTS messages_fts")
    # 老表数据由 rebuild_fts_once() 首次 search 时跑 'rebuild' 命令反向灌回。


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """把 messages 已有行反向灌进 messages_fts。

    external-content FTS5 + 3 triggers 只同步后续 INSERT/UPDATE/DELETE,老行不在索引里,
    不 rebuild 用户搜不到历史消息。
    """
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
