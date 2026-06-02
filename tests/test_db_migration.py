"""测试 db.py 迁移逻辑。"""

import sqlite3

import pytest

from nexus.backend.db import _ensure_column


class TestEnsureColumn:
    """测试 _ensure_column 辅助函数。"""

    @pytest.fixture
    def conn(self):
        """创建一个临时内存数据库，含 messages 表。"""
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                content TEXT
            )
        """)
        yield conn
        conn.close()

    def test_add_missing_column(self, conn: sqlite3.Connection) -> None:
        """列不存在时应添加。"""
        _ensure_column(conn, "messages", "thinking_content", "TEXT")
        rows = conn.execute("PRAGMA table_info(messages)").fetchall()
        columns = {row[1] for row in rows}
        assert "thinking_content" in columns

    def test_skip_existing_column(self, conn: sqlite3.Connection) -> None:
        """列已存在时不应报错，也不应重复添加。"""
        _ensure_column(conn, "messages", "thinking_content", "TEXT")
        # 第二次调用应该是幂等的
        _ensure_column(conn, "messages", "thinking_content", "TEXT")
        rows = conn.execute("PRAGMA table_info(messages)").fetchall()
        # 仍然只有一列 thinking_content
        thinking_columns = [r for r in rows if r[1] == "thinking_content"]
        assert len(thinking_columns) == 1

    def test_default_value_applied(self, conn: sqlite3.Connection) -> None:
        """带 DEFAULT 的列，新插入应使用默认值。"""
        _ensure_column(conn, "messages", "channel", "TEXT DEFAULT 'main'")
        conn.execute("INSERT INTO messages (id, content) VALUES ('m1', 'hi')")
        row = conn.execute("SELECT channel FROM messages WHERE id='m1'").fetchone()
        assert row is not None
        assert row[0] == "main"

    def test_missing_table_raises(self) -> None:
        """表不存在时 PRAGMA table_info 会抛错，不应被吞掉。"""
        conn = sqlite3.connect(":memory:")
        try:
            with pytest.raises(sqlite3.OperationalError):
                _ensure_column(conn, "nonexistent_table", "x", "TEXT")
        finally:
            conn.close()
