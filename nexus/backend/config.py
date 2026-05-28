import os
import json
from pathlib import Path


def load_config() -> dict:
    """从环境变量和配置文件加载配置。"""
    # 从配置文件读取安全配置
    config_path = Path.home() / ".nexus" / "workspace" / "config" / "config.json"
    file_config = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                file_config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    config = {
        "minimax_api_key": os.environ.get("MiniMax_API_KEY", "") or file_config.get("models", [{}])[0].get("api_key", ""),
        "minimax_api_base": os.environ.get("MiniMax_API_BASE", file_config.get("models", [{}])[0].get("api_base", "https://api.minimaxi.com/v1")),
        "model_name": os.environ.get("MODEL_NAME", file_config.get("models", [{}])[0].get("name", "MiniMax-M2.7")),
        "temperature": float(os.environ.get("MODEL_TEMPERATURE", file_config.get("models", [{}])[0].get("temperature", 0.7))),
        "database_url": os.environ.get("DATABASE_URL", str(Path.home() / ".nexus" / "nexus.db")),
        "server_host": os.environ.get("SERVER_HOST", file_config.get("server", {}).get("host", "0.0.0.0")),
        "server_port": int(os.environ.get("SERVER_PORT", file_config.get("server", {}).get("port", "8000"))),
        "default_save_path": os.environ.get("DEFAULT_SAVE_PATH", str(Path.home() / ".nexus" / "workspace" / "outputs")),
        "tavily_api_key": os.environ.get("TAVILY_API_KEY", ""),
        "openweathermap_api_key": os.environ.get("OPENWEATHERMAP_API_KEY", ""),
        "ws_token": os.environ.get("NEXUS_WS_TOKEN", file_config.get("security", {}).get("ws_token", "nexus-default-token")),
        # 工作区目录
        "workspace_root": str(Path.home() / ".nexus" / "workspace"),
        "memory_dir": str(Path.home() / ".nexus" / "workspace" / "memory"),
        "session_corpus_dir": str(Path.home() / ".nexus" / "workspace" / "session-corpus"),
        "uploads_dir": str(Path.home() / ".nexus" / "workspace" / "uploads"),
        "cache_dir": str(Path.home() / ".nexus" / "workspace" / "cache"),
    }

    return config


CONFIG = load_config()