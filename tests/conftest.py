"""pytest 全局测试隔离配置。"""

# ruff: noqa: I001

import pytest

from nexus.backend import config as config_module
from nexus.backend import db
from nexus.backend import models_config


@pytest.fixture(autouse=True)
def isolate_runtime_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """默认隔离运行时文件，避免测试读写真实用户目录。"""
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
