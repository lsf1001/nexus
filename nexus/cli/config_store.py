"""配置存储模块。"""
import json
from pathlib import Path
from typing import Any

NEXUS_CONFIG_PATH = Path.home() / ".nexus" / "config.json"
NEXUS_MODELS_PATH = Path.home() / ".nexus" / "models.json"


def get_default_config() -> dict:
    """返回默认配置。"""
    return {
        "server": {
            "host": "0.0.0.0",
            "port": 30000,
        },
        "models": [
            {
                "id": "default",
                "name": "MiniMax-M2.7",
                "api_key": "",
                "api_base": "https://api.minimaxi.com/v1",
                "temperature": 0.7,
                "is_active": True,
            }
        ],
        "mcp": {
            "enabled": True,
        },
        "security": {
            "ws_token": "nexus-default-token",
        },
    }


def load_nexus_config() -> dict:
    """加载 ~/.nexus/config.json。"""
    if NEXUS_CONFIG_PATH.exists():
        try:
            with open(NEXUS_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # 迁移旧的 models.json
    if NEXUS_MODELS_PATH.exists():
        try:
            with open(NEXUS_MODELS_PATH, encoding="utf-8") as f:
                models_data = json.load(f)
            config = get_default_config()
            config["models"] = models_data.get("models", [])
            save_nexus_config(config)
            return config
        except (json.JSONDecodeError, OSError):
            pass

    return get_default_config()


def save_nexus_config(config: dict) -> None:
    """保存配置到 ~/.nexus/config.json。"""
    NEXUS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(NEXUS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def resolve_config_key(config: dict, key: str) -> Any:
    """解析点分配置键，支持数组索引。

    示例:
        server.port -> 30000
        models[0].api_key -> "sk-..."
    """
    parts = []
    current = ""
    in_bracket = False

    for char in key:
        if char == "[":
            if current:
                parts.append(current)
                current = ""
            in_bracket = True
        elif char == "]":
            if current:
                parts.append(int(current))
                current = ""
            in_bracket = False
        elif char == "." and not in_bracket:
            if current:
                parts.append(current)
                current = ""
        else:
            current += char

    if current:
        parts.append(current)

    value = config
    for part in parts:
        if isinstance(value, dict) and isinstance(part, str):
            value = value.get(part)
        elif isinstance(value, list) and isinstance(part, int):
            if 0 <= part < len(value):
                value = value[part]
            else:
                return None
        else:
            return None

        if value is None:
            return None

    return value


def set_config_key(config: dict, key: str, value: str) -> None:
    """设置配置键值。"""
    parts = []
    current = ""
    in_bracket = False

    for char in key:
        if char == "[":
            if current:
                parts.append(current)
                current = ""
            in_bracket = True
        elif char == "]":
            if current:
                parts.append(int(current))
                current = ""
            in_bracket = False
        elif char == "." and not in_bracket:
            if current:
                parts.append(current)
                current = ""
        else:
            current += char

    if current:
        parts.append(current)

    obj = config
    for i, part in enumerate(parts[:-1]):
        if isinstance(part, int):
            if isinstance(obj, list) and 0 <= part < len(obj):
                obj = obj[part]
        else:
            if part not in obj:
                obj[part] = {}
            obj = obj[part]

    last_part = parts[-1]
    if isinstance(last_part, int):
        if isinstance(obj, list) and 0 <= last_part < len(obj):
            obj[last_part] = value
    else:
        obj[last_part] = value
