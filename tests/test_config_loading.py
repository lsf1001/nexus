"""配置加载回归测试。"""

from __future__ import annotations

import json

import pytest

from nexus.backend import config as config_module
from nexus.backend import db, models_config
from nexus.cli.config_store import get_default_config


_MODEL_ENV_KEYS = (
    "MINIMAX_API_KEY",
    "MiniMax_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "MINIMAX_API_BASE",
    "MiniMax_API_BASE",
    "ANTHROPIC_BASE_URL",
    "MODEL_NAME",
    "MODEL_TEMPERATURE",
)


def _clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清理宿主机模型环境变量，避免污染配置加载断言。"""
    for key in _MODEL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_config_uses_nexus_home_config_and_documented_env(monkeypatch, tmp_path) -> None:
    """后端应读取安装目录配置，并支持文档公开的环境变量名。"""
    nexus_home = tmp_path / ".nexus"
    config_path = nexus_home / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "server": {"host": "127.0.0.1", "port": 31000},
                "security": {"ws_token": "file-token"},
                "models": [
                    {
                        "id": "default",
                        "name": "DocModel",
                        "api_key": "file-key",
                        "api_base": "https://example.invalid/v1",
                        "temperature": 0.2,
                        "is_active": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("NEXUS_HOME", str(nexus_home))
    monkeypatch.setenv("NEXUS_PORT", "32000")
    monkeypatch.setenv("DATABASE_URL", str(tmp_path / "runtime.db"))

    loaded_config = config_module.load_config()

    assert loaded_config["server_host"] == "127.0.0.1"
    assert loaded_config["server_port"] == 32000
    assert loaded_config["ws_token"] == "file-token"
    assert loaded_config["model_name"] == "DocModel"
    assert loaded_config["minimax_api_key"] == "file-key"
    assert loaded_config["db_path"] == str(tmp_path / "runtime.db")


def test_db_path_uses_configured_database_url(monkeypatch, tmp_path) -> None:
    """DB 层应使用配置里的数据库路径，而不是硬编码用户目录。"""
    runtime_db = tmp_path / "configured.db"
    monkeypatch.setitem(db.CONFIG, "database_url", str(runtime_db))
    monkeypatch.delitem(db.CONFIG, "db_path", raising=False)

    assert db._get_db_path() == runtime_db


def test_default_model_is_minimax_m3(monkeypatch, tmp_path) -> None:
    """所有默认配置入口应统一使用 MiniMax-M3。"""
    runtime_dir = tmp_path / ".nexus"
    runtime_dir.mkdir(exist_ok=True)
    models_path = runtime_dir / "models.json"

    monkeypatch.setenv("NEXUS_HOME", str(runtime_dir))
    _clear_model_env(monkeypatch)
    monkeypatch.setattr(models_config, "MODELS_FILE", models_path)

    loaded_config = config_module.load_config()
    loaded_models = models_config.load_models()
    cli_config = get_default_config()

    assert loaded_config["model_name"] == "MiniMax-M3"
    assert loaded_models["models"][0]["name"] == "MiniMax-M3"
    assert cli_config["models"][0]["name"] == "MiniMax-M3"
