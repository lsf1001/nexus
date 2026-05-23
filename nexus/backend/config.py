import os
import json
from pathlib import Path


def load_config() -> dict:
    """从环境变量和配置文件加载配置。"""
    config = {
        "minimax_api_key": os.environ.get("MiniMax_API_KEY", ""),
        "minimax_api_base": os.environ.get("MiniMax_API_BASE", "https://api.minimaxi.com/v1"),
        "database_url": os.environ.get("DATABASE_URL", "./nexus.db"),
        "server_host": os.environ.get("SERVER_HOST", "0.0.0.0"),
        "server_port": int(os.environ.get("SERVER_PORT", "8000")),
    }

    # 如果环境变量未设置，从 ~/.claude/settings.json 读取
    if not config["minimax_api_key"]:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path) as f:
                    settings = json.load(f)
                config["minimax_api_key"] = settings.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
            except Exception:
                pass

    return config


CONFIG = load_config()