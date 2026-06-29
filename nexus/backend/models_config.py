"""``~/.nexus/models.json`` 读写原语 + vendor 推断。

健壮性:
  - 缺文件 → 写入默认 MiniMax-M3 占位
  - 裸 list / 缺 models 键 → 规范化成 ``{"models": [...]}``
  - 原子写:临时文件 + ``os.replace``
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 模型配置文件路径。优先级:NEXUS_HOME 环境变量 > ~/.nexus/models.json。
# WHY:NEXUS_HOME 由 Tauri 桌面端 / 测试 fixture 显式设置,把数据目录和系统 home
# 解耦(避免污染用户 home);desktop install 路径必须可移植,不能假设 macOS user
# home 即可。CI Playwright 也通过 NEXUS_HOME 隔离,修 2026-06-28 27 spec 全 fail。
MODELS_FILE = Path(os.environ.get("NEXUS_HOME") or Path.home()) / ".nexus" / "models.json"


# 域名 → 厂商名映射,只覆盖 Nexus 实际可能接入的 vendor。
# WHY hardcode 这层映射:
#   models.json schema 只有 ``api_base`` URL(无 vendor 字段),真实从 LLM
#   那里拿不到厂商名;LLM 被问"你用的什么模型"时,需要 introspect 真实厂商
#   (MiniMax / agnes-ai / OpenAI / Anthropic),不能瞎猜。
#   域名是稳定锚点 — MiniMax / agnes-ai 都不会轻易换主域。
_VENDOR_BY_HOST: dict[str, str] = {
    "apihub.agnes-ai.com": "agnes-ai",
    "api.minimaxi.com": "MiniMax",
    "api.openai.com": "OpenAI",
    "api.anthropic.com": "Anthropic",
}


def infer_vendor(model: dict[str, Any]) -> str:
    """从 model dict 的 ``api_base`` URL 推断厂商名。

    Args:
        model: 单条模型配置,需含 ``api_base``(URL 字符串)。

    Returns:
        厂商名(``"MiniMax"`` / ``"agnes-ai"`` / ``"OpenAI"`` / ``"Anthropic"``
        等)。无法识别时回退到 ``"未知厂商"`` —— 绝不抛,因为 tool 调用方
        容错性优先,LLM 用空字符串能答"未知厂商"也比崩掉好。
    """
    api_base = (model.get("api_base") or "").strip()
    if not api_base:
        return "未知厂商"
    try:
        host = (urlparse(api_base).hostname or "").lower()
    except ValueError:
        return "未知厂商"
    if not host:
        return "未知厂商"
    return _VENDOR_BY_HOST.get(host, f"未知厂商({host})")


def get_active_model_info() -> dict[str, Any]:
    """返回当前激活模型的完整 info,供 LLM 工具调用时 introspect。

    Returns:
        ``{name, vendor, api_base, temperature, is_active}``;无激活模型时
        返回空 dict(让 LLM 端 fallback 报"未配置模型")。
    """
    model = get_active_model()
    if not model:
        return {}
    return {
        "name": model.get("name", ""),
        "vendor": infer_vendor(model),
        "api_base": model.get("api_base", ""),
        "temperature": model.get("temperature"),
        "is_active": model.get("is_active", False),
    }


def load_models() -> dict[str, Any]:
    """从 ~/.nexus/models.json 加载模型配置。

    健壮性:历史 bug 里有人手动把文件写成 ``[]``(裸 list)或缺失 ``models`` 键,
    load_models 必须返回 ``{"models": [...]}`` 的规范 schema,否则调用方
    的 ``config.get("models")`` 会报 'list' has no attribute 'get'。
    """
    if not MODELS_FILE.exists():
        # E2E 2026-06-29 转圈 bug 修复:文件不存在时**返回内存 default,不写盘**。
        #
        # 之前这里 ``save_models(default_config)`` 会主动创建空 api_key 的
        # default-MiniMax-M3 配置并覆盖磁盘 — 后果:
        #   1. 用户在 UI 切换激活模型后(models.json 含完整 agnes 配置)被覆盖成空 default
        #   2. _ensure_agent_ready 拿空 api_key,走 CONFIG["minimax_api_key"] fallback
        #   3. 后续 LLM 走 minimax,与 UI 标题栏不一致 → "转圈"(用户感)
        #
        # 修正:**只在内存里给 default 配置,绝不写盘**。磁盘文件的创建走显式路径
        # (UI 首次添加模型 / 首次 setup / 现有 save_models 调用方)。返回的 default
        # 故意 ``api_key=""`` — 调用方 (get_active_model → _create_agent_with_model)
        # 看到空 key 会返 None,agent 不被构造;UI 拉 /api/model 拿到 default 模型名
        # 但无 key,正常进 "未配置" 提示状态,不静默 fallback 到 minimax 凭据。
        MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        return {
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
