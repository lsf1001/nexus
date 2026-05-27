import os
import json
from pathlib import Path


def load_config() -> dict:
    """从环境变量和配置文件加载配置。"""
    config = {
        "minimax_api_key": os.environ.get("MiniMax_API_KEY", ""),
        "minimax_api_base": os.environ.get("MiniMax_API_BASE", "https://api.minimaxi.com/v1"),
        "model_name": os.environ.get("MODEL_NAME", "MiniMax-M2.7"),
        "temperature": float(os.environ.get("MODEL_TEMPERATURE", "0.7")),
        "database_url": os.environ.get("DATABASE_URL", "./nexus.db"),
        "server_host": os.environ.get("SERVER_HOST", "0.0.0.0"),
        "server_port": int(os.environ.get("SERVER_PORT", "8000")),
        "default_save_path": os.environ.get("DEFAULT_SAVE_PATH", str(Path.home() / "Documents" / "Nexus")),
        "tavily_api_key": os.environ.get("TAVILY_API_KEY", ""),
        "openweathermap_api_key": os.environ.get("OPENWEATHERMAP_API_KEY", ""),
        "ws_token": os.environ.get("NEXUS_WS_TOKEN", "nexus-default-token"),
    }

    # 从 config.json 加载安全配置
    config_path = Path.home() / ".nexus" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                file_config = json.load(f)
            # 合并 security 配置
            if "security" in file_config:
                if "ws_token" in file_config["security"]:
                    config["ws_token"] = file_config["security"]["ws_token"]
        except (json.JSONDecodeError, IOError):
            pass

    return config


CONFIG = load_config()