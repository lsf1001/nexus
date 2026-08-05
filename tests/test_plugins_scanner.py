"""插件扫描测试。"""

from __future__ import annotations

import json
from pathlib import Path

from nexus.backend.plugins_scanner import scan_plugins


def _plugins_dir(tmp_path: Path) -> Path:
    """创建临时插件目录。"""
    return tmp_path / ".nexus" / "plugins"


def test_scan_empty_dir_returns_empty_list(tmp_path: Path, monkeypatch) -> None:
    """用户尚未创建插件目录时返回空列表。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert scan_plugins() == []


def test_scan_reads_plugin_manifest(tmp_path: Path, monkeypatch) -> None:
    """读取有效 plugin.json 并返回标准字段。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    plugin_dir = _plugins_dir(tmp_path) / "my-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "my-plugin",
                "version": "1.0.0",
                "description": "test",
                "type": "tool",
            }
        ),
        encoding="utf-8",
    )
    result = scan_plugins()
    assert len(result) == 1
    assert result[0]["name"] == "my-plugin"
    assert result[0]["version"] == "1.0.0"
    assert result[0]["description"] == "test"
    assert result[0]["type"] == "tool"
    assert result[0]["path"] == str(plugin_dir)


def test_scan_skips_invalid_json(tmp_path: Path, monkeypatch) -> None:
    """损坏 JSON 不应阻断扫描。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    plugin_dir = _plugins_dir(tmp_path) / "bad"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text("not json{", encoding="utf-8")
    assert scan_plugins() == []


def test_scan_skips_subdirs_without_manifest(tmp_path: Path, monkeypatch) -> None:
    """缺少 manifest 的插件目录被跳过。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (_plugins_dir(tmp_path) / "no-manifest-dir").mkdir(parents=True)
    assert scan_plugins() == []
