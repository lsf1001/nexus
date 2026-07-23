"""Project 子系统 — 对应 SPEC §4。

Public surface:
  - storage:文件系统 + 默认 Project 迁移
  - skills_loader:per-project skills 扫描
  - mcp_loader:per-project mcp.json 加载 + 热更新
"""

from .storage import (
    ensure_default_project,
    migrate_sessions_to_default,
)

__all__ = ["ensure_default_project", "migrate_sessions_to_default"]
