"""per-project system prompt 注入 — SPEC §4.6。

调用方(:mod:`nexus.backend.agent._system_prompt`)拿到 active_project_id,
调本模块 :func:`build_project_context_prompt` 得到
``<project_context>...</project_context>`` 段,append 到 base system prompt。
"""

from __future__ import annotations

from pathlib import Path

from ..db import get_db
from ..projects import storage as _storage
from ..projects.mcp_loader import load_mcp_config_for_project
from ..projects.skills_loader import list_skills

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
    """从 DB 拿 (name, path)。project_id 不存在 → 返回 (未知, 未知)。"""
    with get_db() as conn:
        row = conn.execute("SELECT name, path FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return ("(未知)", "(未知)")
    return (row["name"], row["path"])


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

    return (
        "<project_context>\n"
        f"name: {name}\n"
        f"path: {path}\n"
        f"AGENTS.md: {agents_md}\n"
        f"skills: {skill_names}\n"
        f"mcp_servers: {server_names}\n"
        "</project_context>"
    )
