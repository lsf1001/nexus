"""pytest 全局测试隔离配置。"""

# ruff: noqa: I001

import gc

import pytest

from nexus.backend import agent as agent_module
from nexus.backend import config as config_module
from nexus.backend import db
from nexus.backend import models_config


@pytest.fixture(autouse=True)
def isolate_runtime_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """默认隔离运行时文件，避免测试读写真实用户目录。

    不要 reload ``nexus.backend.config``:``auth.py`` 等模块用
    ``from .config import CONFIG`` 在 import 时绑了 dict 对象,reload 会重
    建 dict 但其它模块的引用仍是旧对象,跨文件测试出现幻性 401。
    """
    runtime_dir = tmp_path / ".nexus"
    runtime_dir.mkdir()
    database_path = runtime_dir / "nexus.db"
    models_path = runtime_dir / "models.json"

    monkeypatch.setenv("NEXUS_HOME", str(runtime_dir))
    monkeypatch.setenv("NEXUS_ENABLE_MCP", "false")
    monkeypatch.setitem(config_module.CONFIG, "db_path", str(database_path))
    monkeypatch.setitem(config_module.CONFIG, "database_url", str(database_path))
    monkeypatch.setattr(db, "_INITED", False)
    monkeypatch.setattr(models_config, "MODELS_FILE", models_path)


@pytest.fixture(autouse=True)
def reset_checkpointer_cache() -> None:
    """每个 case 结束清空 checkpointer 单例,释放 aiosqlite 后台线程。

    WHY:AsyncSqliteSaver 内部持有 aiosqlite 连接,连接里又起了一个非 daemon
    后台线程。如果测试结束时不释放,线程一直存活,pytest 退出挂死。
    清缓存 + gc.collect 触发连接关闭,线程能正常退出。
    """
    yield
    agent_module._reset_checkpointer_cache()
    gc.collect()
