"""checkpointer 从 MemorySaver 升级到 SqliteSaver 的契约测试。

WHY:进程重启会丢挂起 HITL 状态(挂起的 confirmation_request 在新进程里
找不到 checkpoint,用户必须重发提示词)。SqliteSaver 把 checkpoint 写入
``~/.nexus/nexus.db``,跨进程存活。本测试守住:
  - ``create_agent`` 默认用 SqliteSaver(不是 MemorySaver)
  - ``NEXUS_CHECKPOINTER=memory`` 时退化到 MemorySaver(给单元测试用)
  - SqliteSaver 实例两次打开同一 DB 能读到对方写的数据(证明真持久化)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCreateAgentCheckpointer:
    """``create_agent`` 按 env 选 checkpointer 实现。"""

    def test_default_is_sqlite_saver(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """默认(NEXUS_CHECKPOINTER 未设)必须用 AsyncSqliteSaver,挂起状态才能跨进程存活。"""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        monkeypatch.delenv("NEXUS_CHECKPOINTER", raising=False)
        db = tmp_path / "test.db"
        monkeypatch.setenv("NEXUS_DB_PATH", str(db))

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert "checkpointer" in kwargs, "checkpointer kwarg 缺失 — HITL 续流会失败"
            # AsyncSqliteSaver(不是 SqliteSaver)— astream_events 异步路径
            # 走 SqliteSaver 会抛 "does not support async"。这是曾经踩过的坑
            # (e2e_driver 2026-06-25 暴露),测试守住。
            assert isinstance(kwargs["checkpointer"], AsyncSqliteSaver), (
                f"默认必须是 AsyncSqliteSaver,实际是 {type(kwargs['checkpointer']).__name__}"
            )

    def test_memory_saver_when_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``NEXUS_CHECKPOINTER=memory`` 时退化到 MemorySaver(给单测 / 临时场景)。"""
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        monkeypatch.setenv("NEXUS_CHECKPOINTER", "memory")

        from langgraph.checkpoint.memory import MemorySaver

        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert isinstance(kwargs["checkpointer"], MemorySaver)


class TestSqliteSaverPersistence:
    """SqliteSaver 真持久化:两个实例读同一 DB 能共享 checkpoint。"""

    def test_two_savers_share_state(self, tmp_path: Path) -> None:
        """Saver A 写入 → Saver B 读出,证明挂起状态真在磁盘上。"""
        from langgraph.checkpoint.sqlite import SqliteSaver

        db = str(tmp_path / "shared.db")
        thread_id = "test-thread"
        # checkpoint_ns 是 SqliteSaver.put() 必填 key(空串 = 默认 namespace)
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

        # 1) Saver A 写一个 checkpoint
        with SqliteSaver.from_conn_string(db) as saver_a:
            saver_a.setup()  # noqa: ERA001 - langgraph 公共 API
            # 用最小可序列化结构:写一个空 checkpoint 跟 thread 关联
            empty_writes: tuple = ()
            metadata: dict = {}
            # 直接调用底层 put — 暴露在 BaseCheckpointSaver.put_writes / .put
            from langgraph.checkpoint.base import Checkpoint

            checkpoint = Checkpoint(
                v=1,
                id="cp-1",
                ts="2026-06-25T00:00:00+00:00",
                channel_values={},
                channel_versions={},
                versions_seen={},
                pending_sends=[],
            )
            saver_a.put(config, checkpoint, metadata, empty_writes)

        # 2) Saver B 同一 DB 同一 thread 读出来
        with SqliteSaver.from_conn_string(db) as saver_b:
            loaded = saver_b.get_tuple(config)
            assert loaded is not None, "Saver B 读不到 Saver A 写的 checkpoint — 持久化失效"
            assert loaded.checkpoint["id"] == "cp-1"

    def test_table_isolated_from_main_db(self, tmp_path: Path) -> None:
        """SqliteSaver 自己建 checkpoints 表(不污染 sessions / messages 等业务表)。

        WHY:跟 nexus.db 共库,但表名带 langgraph 前缀;业务表 PRAGMA 不会被破坏。
        """
        from langgraph.checkpoint.sqlite import SqliteSaver

        db = tmp_path / "test.db"
        # 先建业务表(模拟 nexus.db 已存在的场景)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO sessions VALUES ('s1')")
            conn.commit()

        with SqliteSaver.from_conn_string(str(db)) as saver:
            saver.setup()  # noqa: ERA001
            # 业务表数据不应被清
            row = conn.execute("SELECT id FROM sessions").fetchone() if False else None
            with sqlite3.connect(db) as check_conn:
                row = check_conn.execute("SELECT id FROM sessions").fetchone()
            assert row[0] == "s1", "SqliteSaver.setup() 不应破坏业务表"
            # checkpoints 表存在
            with sqlite3.connect(db) as check_conn:
                tables = {
                    r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
            assert any("checkpoint" in t.lower() for t in tables), f"应创建 checkpoint 相关表,实际 {tables}"
