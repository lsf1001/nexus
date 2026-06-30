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
        # 必须把 store 也切到 memory,否则默认 AsyncSqliteStore 跟 conftest 的
        # sync sqlite3 同库持锁,create_agent() 在 _create_store() 阶段死锁。
        monkeypatch.setenv("NEXUS_STORE", "memory")

        from langgraph.checkpoint.memory import MemorySaver

        from nexus.backend.agent import create_agent

        with patch("deepagents.create_deep_agent") as mock_create:
            mock_create.return_value = MagicMock()
            create_agent(model_name="m", api_key="k", api_base="https://x")

            kwargs = mock_create.call_args.kwargs
            assert isinstance(kwargs["checkpointer"], MemorySaver)

    def test_default_database_follows_nexus_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """未显式设置 DB 路径时，checkpointer 必须写入 NEXUS_HOME。"""
        nexus_home = tmp_path / "custom-home"
        fallback_home = tmp_path / "fallback-home"
        monkeypatch.setenv("NEXUS_HOME", str(nexus_home))
        monkeypatch.delenv("NEXUS_DB_PATH", raising=False)
        monkeypatch.delenv("NEXUS_CHECKPOINTER", raising=False)
        monkeypatch.setattr("pathlib.Path.home", lambda: fallback_home)

        from nexus.backend.agent import _create_checkpointer

        _create_checkpointer()

        assert (nexus_home / "nexus.db").exists()


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


class TestCheckpointSqliteInPyproject:
    """守门测试:防止 ``langgraph-checkpoint-sqlite`` 依赖被误从 ``pyproject.toml`` 删除。

    WHY:E2E 2026-06-30 暴露 — 干净环境 ``pip install -e .`` 不会装这个子包
    (langgraph / deepagents 都不传递依赖它),导致 ``_create_checkpointer``
    在 import 时 ``ModuleNotFoundError``,agent 懒构造失败,所有依赖 LLM 的
    E2E test 拿到空回复。本测试直接读 ``pyproject.toml`` 校验声明存在,
    比纯靠 import 测试更稳 — import 失败在本地 venv 装过就不暴露,CI 干净
    环境才暴露。
    """

    def test_pyproject_declares_langgraph_checkpoint_sqlite(self) -> None:
        """``pyproject.toml`` 必须显式声明 ``langgraph-checkpoint-sqlite`` 依赖。"""
        import re
        from pathlib import Path

        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        content = pyproject_path.read_text(encoding="utf-8")
        # 匹配 dependencies 段里出现的包名 — 简单 regex 即可,避免引入 toml 解析器
        # 只看 ``dependencies = [ ... ]`` 段(不看 dev / optional)
        # 注意:不能用 non-greedy ``\[(.*?)\]`` — ``uvicorn[standard]`` 里的
        # ``]`` 会让匹配提前结束,只匹配到 ``uvicorn[standard`` 就停下。
        # 用 greedy + DOTALL 找最后那个 ``]``(更鲁棒)。
        match = re.search(r"^dependencies\s*=\s*\[(.*)\]", content, re.MULTILINE | re.DOTALL)
        assert match is not None, "pyproject.toml 缺少 dependencies 段"
        deps_block = match.group(1)
        # 包名可能带版本约束也可能不带,匹配裸包名 + 任何后续规格
        pattern = re.compile(r"""["'](langgraph-checkpoint-sqlite)(?:\s*[><=!~].*?)?["']""")
        assert pattern.search(deps_block) is not None, (
            "pyproject.toml dependencies 必须显式声明 langgraph-checkpoint-sqlite, "
            "否则干净环境 pip install -e . 会漏装,导致 _create_checkpointer "
            "ModuleNotFoundError,所有 LLM E2E test 拿空回复"
        )

    def test_checkpoint_sqlite_module_importable(self) -> None:
        """干净 venv 必须能 import AsyncSqliteSaver,否则 checkpoint 初始化失败。

        配合 TestPyprojectDeclaresLanggraphCheckpointSqlite 一起守门:
          - 第一个测试保证 ``pyproject.toml`` 写对了
          - 第二个测试保证**当前 venv** 已经按声明装上了
        """
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: F401
        except ModuleNotFoundError as e:
            pytest.fail(
                f"AsyncSqliteSaver 不可 import — pyproject.toml 漏声明 langgraph-checkpoint-sqlite?原始错误: {e}"
            )
