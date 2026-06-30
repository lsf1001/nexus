import json
import os
import tempfile
from pathlib import Path
from typing import Any

# 模型配置文件路径。优先级:NEXUS_HOME 环境变量 > ~/.nexus/models.json。
# WHY:NEXUS_HOME 由 Tauri 桌面端 / 测试 fixture 显式设置,把数据目录和系统 home
# 解耦(避免污染用户 home);desktop install 路径必须可移植,不能假设 macOS user
# home 即可。CI Playwright 也通过 NEXUS_HOME 隔离,修 2026-06-28 27 spec 全 fail。
MODELS_FILE = Path(os.environ.get("NEXUS_HOME") or Path.home()) / ".nexus" / "models.json"


def load_models() -> dict[str, Any]:
    """从 ~/.nexus/models.json 加载模型配置。

    健壮性:历史 bug 里有人手动把文件写成 ``[]``(裸 list)或缺失 ``models`` 键,
    load_models 必须返回 ``{"models": [...]}`` 的规范 schema,否则调用方
    的 ``config.get("models")`` 会报 'list' has no attribute 'get'。
    """
    if not MODELS_FILE.exists():
        MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        default_config = {
            "models": [
                {
                    "id": "default",
                    "name": "MiniMax-M3",
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
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"models": []}

    # 规范化: 裸 list / 缺 models 键 / 不是 dict 都修成 {"models": [...]}
    if not isinstance(data, dict):
        # 裸 list 或其它类型 → 包成 dict
        if isinstance(data, list):
            return {"models": data}
        return {"models": []}
    if "models" not in data or not isinstance(data["models"], list):
        data["models"] = []
    return data


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
