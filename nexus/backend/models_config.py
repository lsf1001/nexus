import json
import os
import tempfile
from pathlib import Path
from typing import Any

MODELS_FILE = Path.home() / ".nexus" / "models.json"


def load_models() -> dict[str, Any]:
    """从 ~/.nexus/models.json 加载模型配置。"""
    if not MODELS_FILE.exists():
        MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        default_config = {
            "models": [
                {
                    "id": "default",
                    "name": "MiniMax-M2.7",
                    "api_key": "",
                    "api_base": "https://api.minimaxi.com/v1",
                    "temperature": 0.7,
                    "is_active": True,
                }
            ]
        }
        save_models(default_config)
        return default_config

    try:
        with open(MODELS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"models": []}


def save_models(config: dict[str, Any]) -> None:
    """原子保存模型配置到 ~/.nexus/models.json。

    先写到同目录下临时文件，再 os.replace 原子替换，避免写入中途崩溃损坏配置。
    """
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(MODELS_FILE.parent), prefix=".models.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, MODELS_FILE)
    except Exception:
        # 清理临时文件，避免遗留
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def get_active_model() -> dict[str, Any] | None:
    """获取当前激活的模型。"""
    config = load_models()
    for model in config.get("models", []):
        if model.get("is_active"):
            return model
    return None


def set_active_model(model_id: str) -> dict[str, Any] | None:
    """设置激活的模型。"""
    config = load_models()
    for model in config.get("models", []):
        model["is_active"] = model.get("id") == model_id
    save_models(config)
    return get_active_model()
