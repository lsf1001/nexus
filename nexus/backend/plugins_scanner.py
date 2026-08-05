"""扫描 ~/.nexus/plugins/ 读取 manifest。

只读,不执行 manifest 中的钩子 — 本轮仅 PreferencesModal 列表展示。
WHY 单独 module 不放 routes/:扫描是 IO + 解析,跟 API 路由解耦便于
后续在 build_agent / skills_loader 等场景复用。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


PLUGINS_DIR = Path.home() / ".nexus" / "plugins"


def _default_plugins_dir() -> Path:
    """默认扫描目录,惰性求值以兼容 monkeypatch(Path.home) 的测试。"""
    return Path.home() / ".nexus" / "plugins"


def scan_plugins(plugins_dir: Path | None = None) -> list[dict]:
    """扫描目录下的所有 <plugin>/plugin.json,返回 manifest 列表。

    行为契约:
      - 目录不存在 → 返回 [],不报错(用户首次启动没建过是合法状态)
      - 子目录无 plugin.json → 跳过
      - plugin.json 解析失败 → log warning + 跳过,不抛
      - 任何字段缺失 → 用默认值 fallback(name=dirname, version="0.0.0", etc.)

    Returns:
        list of dict:每条含 name / version / description / type / path,
        按 name 排序。(name 用于 React key,稳定顺序方便 diff)
    """
    if plugins_dir is None:
        plugins_dir = _default_plugins_dir()
    if not plugins_dir.is_dir():
        return []
    results: list[dict] = []
    for entry in plugins_dir.iterdir():
        if not entry.is_dir():
            continue
        manifest = entry / "plugin.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("跳过 plugin manifest 解析失败: %s (%s)", manifest, exc)
            continue
        if not isinstance(data, dict):
            logger.warning("plugin.json 必须是 JSON object: %s", manifest)
            continue
        results.append(
            {
                "name": str(data.get("name", entry.name)),
                "version": str(data.get("version", "0.0.0")),
                "description": str(data.get("description", "")),
                "type": str(data.get("type", "unknown")),
                "path": str(entry),
            }
        )
    return sorted(results, key=lambda p: p["name"])
