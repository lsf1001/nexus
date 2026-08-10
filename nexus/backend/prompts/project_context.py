"""per-project system prompt 注入 — SPEC §4.6。

调用方(:mod:`nexus.backend.agent._system_prompt`)拿到 active_project_id,
调本模块 :func:`build_project_context_prompt` 得到
``<project_context>...</project_context>`` 段,append 到 base system prompt。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..db import get_db
from ..projects import storage as _storage
from ..projects.mcp_loader import load_mcp_config_for_project
from ..projects.skills_loader import list_skills

logger = logging.getLogger(__name__)

# 默认 Project id — SPEC §4.2。project_id 找不到时回退到此 Project 拿 meta。
_DEFAULT_PROJECT_ID = "default"

# AGENTS.md 截断上限 — 防止恶意/失控的 user-level 记忆把 system prompt 撑爆。
# 200 行 ≈ 8KB,deepagents 体系内 system prompt 总预算 32KB,留足余量给
# identity / skills / mcp 等其它段。
_AGENTS_MD_MAX_LINES = 200


def _projects_root() -> Path:
    """代理 ``storage._projects_root()`` — 便于测试 monkeypatch 本函数重定向根。"""
    return _storage._projects_root()


def _agents_md_for(project_id: str) -> str:
    """读 Project 的 AGENTS.md,截断到 200 行。"""
    path = _projects_root() / project_id / "AGENTS.md"
    if not path.exists():
        return "(无)"
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    if total > _AGENTS_MD_MAX_LINES:
        lines = lines[:_AGENTS_MD_MAX_LINES]
        lines.append(f"... [截断,原文共 {total} 行]")
    return "\n".join(lines)


def _project_meta(project_id: str) -> tuple[str, str]:
    """从 DB 拿 (name, path)。

    project_id 找不到时:记 warning(便于排查),并 fallback 到默认 Project
    (``default``)的 meta,而非静默返回 "(未知)"。若连默认 Project 也查不到
    (极端场景,如 DB 未初始化),才退回 ("(未知)", "(未知)")。
    """
    row = _query_project_row(project_id)
    if row is not None:
        return (row["name"], row["path"])

    logger.warning(
        "project meta 未找到 project_id=%s(active=%s),fallback 到默认 project=%s",
        project_id,
        _storage.read_active_project_id(),
        _DEFAULT_PROJECT_ID,
    )
    if project_id == _DEFAULT_PROJECT_ID:
        # 传入的就是 default 却查不到 → 无更好兜底,直接返回未知。
        return ("(未知)", "(未知)")
    fallback_row = _query_project_row(_DEFAULT_PROJECT_ID)
    if fallback_row is not None:
        return (fallback_row["name"], fallback_row["path"])
    return ("(未知)", "(未知)")


def _query_project_row(project_id: str) -> object | None:
    """按 id 查 projects 表单行;不存在返回 None。"""
    with get_db() as conn:
        return conn.execute("SELECT name, path FROM projects WHERE id = ?", (project_id,)).fetchone()


def build_project_context_prompt(project_id: str) -> str:
    """构造 ``<project_context>`` XML 段。

    段内含 6 行:
      - name:Project 显示名(从 DB 拿)
      - path:Project 目录绝对路径
      - AGENTS.md:Project 级 Agent 记忆内容(截断到 200 行)
      - skills:可用 skill 名列表
      - mcp_servers:已配置的 MCP server 名列表

    WHY 用 XML 段而非 JSON:与现有 identity / skills 段风格一致,
    XML 标签利于 LLM 解析边界,后续 agent 替换 / 注入更直观。
    """
    name, path = _project_meta(project_id)
    agents_md = _agents_md_for(project_id)
    skills = list_skills(project_id)
    mcp_servers = load_mcp_config_for_project(project_id)
    skill_names = [s["name"] for s in skills]
    server_names = [s["name"] for s in mcp_servers]

    # WHY json.dumps 而非 Python list repr:repr 会输出单引号 ['a', 'b'],
    # LLM 易误判为字符串字面量;JSON 双引号数组更规范,与 path 等字段风格一致。
    return (
        "<project_context>\n"
        f"name: {name}\n"
        f"path: {path}\n"
        f"AGENTS.md: {agents_md}\n"
        f"skills: {json.dumps(skill_names, ensure_ascii=False)}\n"
        f"mcp_servers: {json.dumps(server_names, ensure_ascii=False)}\n"
        "</project_context>"
    )
