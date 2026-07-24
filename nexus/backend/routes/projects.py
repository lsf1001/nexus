"""Project REST API — SPEC §4.3。

端点:
  - GET    /api/projects              列出所有 Project
  - GET    /api/projects/{id}         拿单个 Project 详情
  - POST   /api/projects              新建 Project
  - POST   /api/projects/{id}/activate 标记 active + 落盘到 ~/.nexus/active_project.json
  - GET    /api/projects/active       读取当前 active Project id

WHY active 状态先落盘:SPEC §4.7 要求 store.activeProjectId 持久化,
后端作为"权威源"。本轮做"前端 UI 切换 + 后端写盘"路径,
真正的 skills/mcp 热重载留给后续轮。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..api.ws import require_token
from ..config import _get_nexus_home
from ..db import get_db
from ..projects.storage import _projects_root

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_token)],
)

# slug 规则:小写字母数字开头,后续 0-31 个字符可以是字母/数字/-/_。
# 总长度上限 32。前端 SLUG_RE 同步(详见 ProjectDropdown / NewProjectDrawer)。
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,31}$")


def _validate_slug(name: str) -> None:
    """slug 不合法 → 400。422 是 Pydantic 校验风格;本函数是自定义前置,
    报错用 400 维持 plan 契约。
    """
    if not _SLUG_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name 必须匹配 ^[a-z0-9][a-z0-9-_]{0,31}$",
        )


def _row_to_dict(row: Any) -> dict[str, Any]:
    """sqlite3.Row → dict,epoch ms → ISO string。"""
    d = dict(row)
    for key in ("created_at", "updated_at"):
        val = d.get(key)
        if isinstance(val, int):
            d[key] = datetime.fromtimestamp(val / 1000, tz=UTC).isoformat()
    return d


def _ensure_project_dirs(project_path: Path, display_name: str) -> None:
    """新建 Project 时一次性把目录 / AGENTS.md / skills / mcp.json 初始化好。

    WHY skills 是真目录不是软链:用户自建 Project 的 skills 应该跟 default
    解耦(软链到 ~/.nexus/skills 会让两个 Project 的 skills 混在一起,
    违反 SPEC §4.4 per-project 边界)。
    """
    project_path.mkdir(parents=True)
    (project_path / "AGENTS.md").write_text(
        f"# {display_name}\n\n"
        f"本 Project 由用户于 {time.strftime('%Y-%m-%d %H:%M')} 创建。\n"
        "你可以自由编辑本文件,内容会被自动注入会话上下文。\n",
        encoding="utf-8",
    )
    (project_path / "skills").mkdir()
    (project_path / "mcp.json").write_text(
        json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@router.get("")
async def list_projects() -> list[dict[str, Any]]:
    """列出所有 Project,按 created_at 升序(default 在前)。"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/active")
async def get_active_project() -> dict[str, Any] | None:
    """返回当前 active Project 信息;文件不存在或破损 → None。

    前端 fallback:None 时用 store.projects[0]?.id ?? 'default'。
    """
    active_file = _get_nexus_home() / "active_project.json"
    if not active_file.exists():
        return None
    try:
        return json.loads(active_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    """单个 Project 详情;不存在 → 404。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return _row_to_dict(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: dict[str, Any]) -> dict[str, Any]:
    """新建 Project:校验 slug → 唯一性预检 → 建目录 → 写 DB。

    失败模式:
      - slug 不合法 → 400
      - name 重复 → 409
      - 目录已存在(用户手建但 DB 没记录) → 409
    """
    name_raw = body.get("name", "")
    name = name_raw.strip() if isinstance(name_raw, str) else ""
    _validate_slug(name)
    display_name = (body.get("display_name") or name).strip()
    description = (body.get("description") or "").strip()

    # 唯一性预检:DB 层面 UNIQUE 也会兜底,但预检能给出清晰的错误。
    with get_db() as conn:
        dup = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        if dup is not None:
            raise HTTPException(status_code=409, detail=f"Project '{name}' 已存在")

    project_path = _projects_root() / name
    if project_path.exists():
        raise HTTPException(status_code=409, detail=f"目录已存在: {project_path}")

    try:
        _ensure_project_dirs(project_path, display_name)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"创建目录失败: {exc}") from exc

    now = int(time.time() * 1000)
    # slug 即 id:简化命名,避免重复 id 空间。
    project_id = name
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO projects "
                "(id, name, display_name, path, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    name,
                    display_name,
                    str(project_path),
                    description,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # DB UNIQUE 兜底:理论上预检已挡住,但并发场景下仍可能命中。
            raise HTTPException(status_code=409, detail=f"Project '{name}' 已存在") from exc
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    assert row is not None  # 刚 INSERT,不会 None
    return _row_to_dict(row)


@router.post("/{project_id}/activate")
async def activate_project(project_id: str) -> dict[str, str]:
    """标记某 Project 为 active,落盘到 ~/.nexus/active_project.json。

    WHY 原子写(tmp + replace):避免半截 JSON 导致下次启动读到 SyntaxError。
    """
    with get_db() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Project 不存在")

    active_file = _get_nexus_home() / "active_project.json"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"active_project_id": project_id})
    tmp = active_file.with_suffix(".json.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(active_file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入 active_project.json 失败: {exc}") from exc
    return {"active_project_id": project_id}
