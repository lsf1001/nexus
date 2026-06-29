"""models_config.load_models 行为回归测试。

E2E 2026-06-29 暴露的"转圈"bug 根因:
  ``load_models()`` 在 ``~/.nexus/models.json`` 不存在时,主动
  ``save_models(default_config)`` 写一份空 api_key 的 default-MiniMax-M3
  配置。后果:
    1. 用户在 UI 切换激活模型后(models.json 写盘)被覆盖
    2. _ensure_agent_ready 拿空 api_key → 走 minimax fallback
    3. 后续 LLM 走 minimax,UI 标题栏显示 agnes,不一致 → 用户转圈
    4. 即使 UI 重新添加模型,set_active_model 改 dict 时 is_active=True
       的 MiniMax-M3 也在 list 里,下次重启还是被覆盖

修正后契约:
  - 文件不存在 → 返回内存 default,**绝不写盘**
  - 后续 UI 首次添加模型会走 save_models 写盘(显式路径)
  - 默认 default 故意 api_key="",让 _create_agent_with_model 返 None,
    agent 不构造 → UI "未配置模型" 提示,不再静默 fallback
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_models_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 MODELS_FILE / MODELS_DIR 临时指向 sandbox 目录,避免污染用户配置。"""
    from nexus.backend import models_config

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sandbox_file = tmp_path / "models.json"
        # 不创建文件 — 模拟"用户首次启动,文件不存在"
        monkeypatch.setattr(models_config, "MODELS_FILE", sandbox_file)
        yield tmp_path


def test_load_models_when_file_missing_returns_default_without_writing(
    isolated_models_dir: Path,
) -> None:
    """文件不存在 → load_models 返内存 default,**不创建文件**。"""
    from nexus.backend import models_config

    sandbox_file = isolated_models_dir / "models.json"
    assert not sandbox_file.exists()

    config = models_config.load_models()

    # 返回的 config 是规范 schema
    assert isinstance(config, dict)
    assert "models" in config
    assert len(config["models"]) == 1
    default = config["models"][0]
    assert default["id"] == "default"
    assert default["name"] == "MiniMax-M3"
    assert default["api_key"] == ""  # 故意空 → 上游拿空 key 不构造 agent
    assert default["is_active"] is True

    # 关键:文件**没**被创建(避免覆盖用户后续配置)
    assert not sandbox_file.exists(), f"BUG 回归:load_models() 不应写盘,但 {sandbox_file} 已被创建"


def test_get_active_model_when_file_missing_returns_default_dict(
    isolated_models_dir: Path,
) -> None:
    """get_active_model 在文件不存在时也返 default(给 UI /api/model 用)。"""
    from nexus.backend import models_config

    active = models_config.get_active_model()
    assert active is not None
    assert active["id"] == "default"
    assert active["name"] == "MiniMax-M3"
    assert active["api_key"] == ""


def test_load_models_when_file_exists_preserves_user_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """文件存在 → load_models 读用户配置,不覆盖。"""
    from nexus.backend import models_config

    sandbox_file = tmp_path / "models.json"
    user_config = {
        "models": [
            {
                "id": "user-model-1",
                "name": "agnes-2.0-flash",
                "api_key": "sk-user-key",
                "api_base": "https://apihub.agnes-ai.com/v1",
                "temperature": 0.7,
                "is_active": True,
            }
        ]
    }
    sandbox_file.write_text(json.dumps(user_config), encoding="utf-8")

    monkeypatch.setattr(models_config, "MODELS_FILE", sandbox_file)

    config = models_config.load_models()

    # 用户配置原样返回,没被覆盖成 default
    assert config["models"][0]["id"] == "user-model-1"
    assert config["models"][0]["api_key"] == "sk-user-key"

    # 文件 mtime 没变(没被改写)
    on_disk = json.loads(sandbox_file.read_text(encoding="utf-8"))
    assert on_disk["models"][0]["id"] == "user-model-1"
