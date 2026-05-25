import json
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
    except Exception:
        return {"models": []}


def save_models(config: dict[str, Any]) -> None:
    """保存模型配置到 ~/.nexus/models.json。"""
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MODELS_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


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
