import json
import os
from pathlib import Path


def _pick_default_model(file_config: dict) -> dict:
    """从 file_config 的 models 列表中挑选默认模型。

    优先取 is_active=True 的；都没有则退回到第一个；都没有则返回空 dict。
    """
    models = file_config.get("models") or [{}]
    for m in models:
        if m.get("is_active"):
            return m
    return models[0] if models else {}


def load_config() -> dict:
    """从环境变量和配置文件加载配置。"""
    # 从配置文件读取安全配置
    config_path = Path.home() / ".nexus" / "workspace" / "config" / "config.json"
    file_config = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                file_config = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    default_model = _pick_default_model(file_config)

    config = {
        "minimax_api_key": (
            os.environ.get("MINIMAX_API_KEY")
            or os.environ.get("MiniMax_API_KEY")  # 向后兼容旧名
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")  # 兼容 Anthropic 风格 env
            or os.environ.get("ANTHROPIC_API_KEY")
            or default_model.get("api_key", "")
        ),
        "minimax_api_base": (
            os.environ.get("MINIMAX_API_BASE")
            or os.environ.get("MiniMax_API_BASE")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or default_model.get("api_base", "https://api.minimaxi.com/v1")
        ),
        "model_name": os.environ.get("MODEL_NAME", default_model.get("name", "MiniMax-M2.7")),
        "temperature": float(os.environ.get("MODEL_TEMPERATURE", default_model.get("temperature", 0.7))),
        "database_url": os.environ.get("DATABASE_URL", str(Path.home() / ".nexus" / "nexus.db")),
        "server_host": os.environ.get("SERVER_HOST", file_config.get("server", {}).get("host", "0.0.0.0")),
        "server_port": int(os.environ.get("SERVER_PORT", file_config.get("server", {}).get("port", "8000"))),
        "default_save_path": os.environ.get("DEFAULT_SAVE_PATH", str(Path.home() / ".nexus" / "workspace" / "outputs")),
        "tavily_api_key": os.environ.get("TAVILY_API_KEY", ""),
        "openweathermap_api_key": os.environ.get("OPENWEATHERMAP_API_KEY", ""),
        "ws_token": os.environ.get(
            "NEXUS_WS_TOKEN", file_config.get("security", {}).get("ws_token", "nexus-default-token")
        ),
        # 工作区目录
        "workspace_root": str(Path.home() / ".nexus" / "workspace"),
        "memory_dir": str(Path.home() / ".nexus" / "workspace" / "memory"),
        "session_corpus_dir": str(Path.home() / ".nexus" / "workspace" / "session-corpus"),
        "uploads_dir": str(Path.home() / ".nexus" / "workspace" / "uploads"),
        "cache_dir": str(Path.home() / ".nexus" / "workspace" / "cache"),
    }

    return config


CONFIG = load_config()
