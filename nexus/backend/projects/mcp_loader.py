"""per-project MCP 加载 — SPEC §4.5 / §5.2。

策略:不重写 :func:`nexus.backend.mcp.find_mcp_config`,只在本模块提供
"按 project 拿原始 server list" 的 helper。调用方(REST 端点 / agent 热重建)
在切 project 时调它,取得新 server list 后再走原有 ``_load_tools_for_server`` 路径。

WHY 不直接重写 find_mcp_config:那个函数已被 main.py 启动期调用,
    改签名会引发连锁回归。本期方案保留旧函数兼容默认 project,
    新增 per-project loader 给"运行时切 project"的路径用。

失败容忍:mcp.json 缺失 / 损坏 → 空 list,**不抛**(与 skills_loader 同风格),
    避免阻断 REST 调用或 agent 构造。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import _get_nexus_home
from .storage import _projects_root

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> dict[str, Any]:
    """读并解析 mcp.json,失败返回空 dict(记 warning,不抛)。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("MCP 配置 %s 解析失败: %s", path, exc)
        return {}


def find_project_mcp_config(project_id: str) -> list[Path]:
    """列出 project_id 对应的 mcp.json 路径(可能多条,按优先级),只返回存在的。

    - ``default`` project 降级顺序(向后兼容旧安装):
        1. ``~/.nexus/mcp/config.json``(新版)
        2. ``~/.mcp.json``(旧版)
        3. ``~/Nexus/projects/default/mcp.json``
    - 其它 project:``~/Nexus/projects/<name>/mcp.json``

    WHY 保留三级降级:老用户的 MCP 配置散落在 ~/.nexus 与 ~/,
        新用户走 project 目录,统一在这里兜底,避免调用方各自判断。
    """
    if project_id == "default":
        candidates = [
            _get_nexus_home() / "mcp" / "config.json",
            Path.home() / ".mcp.json",
            _projects_root() / "default" / "mcp.json",
        ]
    else:
        candidates = [_projects_root() / project_id / "mcp.json"]
    return [p for p in candidates if p.exists()]


def load_mcp_config_for_project(project_id: str) -> list[dict[str, Any]]:
    """解析 project 的 mcp.json,返回 mcpServers 的 list(每项加 name/source)。

    返回结构与 :func:`nexus.backend.mcp.find_mcp_config` 对齐(含 ``name`` /
    ``source`` 字段),便于调用方直接喂给现有 ``_load_tools_for_server``。

    Args:
        project_id: Project 的 id(``default`` / 用户新建的 slug)。

    Returns:
        list of server config dict;不存在 / 损坏 → 空 list。
    """
    out: list[dict[str, Any]] = []
    for cfg_path in find_project_mcp_config(project_id):
        data = _read_json(cfg_path)
        servers = data.get("mcpServers") or {}
        if not isinstance(servers, dict):
            logger.warning("MCP 配置 %s 的 mcpServers 非 dict,已忽略", cfg_path)
            continue
        for name, server_cfg in servers.items():
            if not isinstance(server_cfg, dict):
                continue
            entry = dict(server_cfg)
            entry["name"] = name
            entry["source"] = str(cfg_path)
            out.append(entry)
    return out
