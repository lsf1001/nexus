"""``scripts/migrate_legacy_memory.py`` 数据迁移脚本契约测试。

WHY: 旧 nexus.db 的 ``memory`` 表是用户历史偏好所在,deepagents 重构
后不能丢。脚本必须:只迁 explicit 类型、改表名 memory_legacy、幂等。
本测试覆盖 4 个契约点,防止回滚或脚本 bug 静默丢数据。
"""

from __future__ import annotations

import importlib
import sqlite3

# 加载脚本模块(非 tests 包内,但通过项目根 /scripts/ 路径 sys.path 注入)
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import migrate_legacy_memory as mlm  # noqa: E402


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """建一个含 memory 表 + 2 explicit + 1 session 行的临时 db。"""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            is_active INTEGER DEFAULT 1,
            access_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        "INSERT INTO memory(memory_type,category,key,value) VALUES (?,?,?,?)",
        ("explicit", "response_style", "prefer_concise", "1"),
    )
    conn.execute(
        "INSERT INTO memory(memory_type,category,key,value) VALUES (?,?,?,?)",
        ("explicit", "tool_preference", "default_editor", "vim"),
    )
    conn.execute(
        "INSERT INTO memory(memory_type,category,key,value) VALUES (?,?,?,?)",
        ("session", "context", "last_topic", "Rust ownership"),
    )
    conn.execute(
        "INSERT INTO memory(memory_type,category,key,value) VALUES (?,?,?,?)",
        ("evolved", "auto_distill", "draft", "用户偏好简洁"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def user_agents_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """monkeypatch 脚本里的 USER_AGENTS_MD 常量指向 tmp 文件。"""
    target = tmp_path / "AGENTS.md"
    monkeypatch.setattr(mlm, "USER_AGENTS_MD", target)
    return target


class TestMigrateExplicit:
    """主流程:explicit 行 → AGENTS.md,表名 → memory_legacy。"""

    def test_explicit_rows_appended_to_agents_md(self, fresh_db: Path, user_agents_md: Path) -> None:
        mlm.run(fresh_db, dry_run=False)
        content = user_agents_md.read_text(encoding="utf-8")
        assert "## Migrated Preferences" in content
        assert "[response_style] prefer_concise: 1" in content
        assert "[tool_preference] default_editor: vim" in content

    def test_non_explicit_rows_skipped(self, fresh_db: Path, user_agents_md: Path) -> None:
        mlm.run(fresh_db, dry_run=False)
        content = user_agents_md.read_text(encoding="utf-8")
        # session / evolved 不进 AGENTS.md
        assert "last_topic" not in content
        assert "draft" not in content

    def test_memory_table_renamed_to_memory_legacy(self, fresh_db: Path, user_agents_md: Path) -> None:
        mlm.run(fresh_db, dry_run=False)
        conn = sqlite3.connect(str(fresh_db))
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()
        assert "memory_legacy" in tables
        assert "memory" not in tables

    def test_memory_legacy_data_intact(self, fresh_db: Path, user_agents_md: Path) -> None:
        """改名后原数据(全 4 行)仍在 memory_legacy,只是表名换了。"""
        mlm.run(fresh_db, dry_run=False)
        conn = sqlite3.connect(str(fresh_db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM memory_legacy").fetchone()[0]
        finally:
            conn.close()
        assert count == 4


class TestMigrateIdempotent:
    """重跑脚本不应该重复追加 / 报错。"""

    def test_rerun_no_op(self, fresh_db: Path, user_agents_md: Path) -> None:
        mlm.run(fresh_db, dry_run=False)
        first = user_agents_md.read_text(encoding="utf-8")
        # 第二次跑:memory 表已经改名 memory_legacy → 应该识别并跳过
        mlm.run(fresh_db, dry_run=False)
        second = user_agents_md.read_text(encoding="utf-8")
        assert first == second, "第二次跑不应重复追加 Migrated Preferences 段"


class TestMigrateDryRun:
    """``--dry-run`` 不写 db、不写文件。"""

    def test_dry_run_writes_nothing(self, fresh_db: Path, user_agents_md: Path) -> None:
        assert not user_agents_md.exists()
        mlm.run(fresh_db, dry_run=True)
        # AGENTS.md 未创建
        assert not user_agents_md.exists()
        # memory 表未被改名
        conn = sqlite3.connect(str(fresh_db))
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()
        assert "memory" in tables
        assert "memory_legacy" not in tables


class TestMigrateNoOpPaths:
    """不存在 / 已迁过的场景不报错。"""

    def test_missing_db_returns_zero(self, tmp_path: Path) -> None:
        """db 文件不存在 → 视为首次安装,直接退出 0。"""
        missing = tmp_path / "no.db"
        assert not missing.exists()
        result = mlm.run(missing, dry_run=False)
        assert result == 0

    def test_no_memory_table_returns_zero(self, tmp_path: Path, user_agents_md: Path) -> None:
        """db 存在但没有 memory 表(用户只用了 sessions)→ 不报错。"""
        db_path = tmp_path / "no_memory.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        result = mlm.run(db_path, dry_run=False)
        assert result == 0


def test_module_reload_safe() -> None:
    """``importlib.reload`` 不能炸,CLI 调用方常见模式。"""
    importlib.reload(mlm)
    assert hasattr(mlm, "run")
