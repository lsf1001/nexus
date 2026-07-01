"""验证 _create_tables 抛异常时,_INITED flag 会被重置,下次 get_db() 会重试。

Bug 历史:``get_db`` 早期实现是 ``_INITED = True; _create_tables(conn)``,
如果 ``_create_tables`` 抛异常,_INITED 已经被置 True,后续同进程再调
``get_db()`` 会跳过建表,导致永远拿到一张未初始化的库。
典型场景:lifespan 重启 / 测试 setup 重入 / 启动期 transient 故障。

修复:把 ``_INITED = True`` 移到 ``_create_tables`` 成功分支之后,失败时
回滚 flag 并 rollback 已开事务,允许同进程重试。

本测试:
  - 第一次 ``_create_tables`` 抛 OperationalError → 第二次 ``get_db()`` 必须
    再调一次 ``_create_tables``(retry)。
  - 正常路径下 ``_create_tables`` 只被调一次(cached path 不重入)。
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from nexus.backend import db


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """每个测试用独立 DB 文件 + 重置 _INITED。conftest 已自动重置 _INITED,
    这里只额外隔离 DB_PATH,避免复用 conftest 默认 tmp_path 之外的路径。
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)


def test_inited_flag_resets_when_create_tables_fails(isolated_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_tables 失败 → _INITED 重置 → 下次 get_db() 重试。"""
    calls = {"create": 0}

    def _flaky_create(conn: sqlite3.Connection) -> None:
        calls["create"] += 1
        if calls["create"] == 1:
            raise sqlite3.OperationalError("simulated DDL failure")

    with patch.object(db, "_create_tables", _flaky_create):
        # 第一次:必须抛 OperationalError
        with pytest.raises(sqlite3.OperationalError):
            with db.get_db():
                pass

        # _INITED 必须被回滚成 False,否则第二次会跳过 _create_tables
        assert db._INITED is False, "_create_tables 失败后 _INITED 必须被重置为 False"

        # 第二次:必须重新尝试 _create_tables
        with db.get_db():
            pass

    assert calls["create"] == 2, "第二次 get_db() 必须重试 _create_tables"


def test_inited_persists_when_create_tables_succeeds(isolated_db: None) -> None:
    """_create_tables 成功 → _INITED 保持 True → 下次 get_db() 跳过。"""
    calls = {"create": 0}

    def _create(conn: sqlite3.Connection) -> None:
        calls["create"] += 1

    with patch.object(db, "_create_tables", _create):
        with db.get_db():
            pass
        with db.get_db():
            pass

    assert db._INITED is True, "成功路径下 _INITED 必须保持 True"
    assert calls["create"] == 1, "成功路径下 _create_tables 必须只被调用一次"
