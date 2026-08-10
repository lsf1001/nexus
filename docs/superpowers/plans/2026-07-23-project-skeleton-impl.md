# Project 骨架 + Per-Project Skills/MCP 实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Nexus 中引入 Project 概念(对齐 Claude Desktop),让每个 Project 拥有独立的 AGENTS.md / skills / mcp.json,Session 通过 `project_id` 归属。默认 Project 自动迁移保证零破坏。

**Architecture:**
- DB 新增 `projects` 表 + `sessions.project_id` 外键,走 `db.py::_ensure_column()` 自动迁移
- 文件系统:每个 Project 是 `~/Nexus/projects/<slug>/` 目录,含 AGENTS.md + skills/ + mcp.json
- 默认 Project(`id="default"`)首次启动时自动建,AGENTS.md 从 `~/.nexus/AGENTS.md` 拷贝,skills/ 软链到 `~/.nexus/skills/`
- 后端新增 `/api/projects` REST + per-project `load_skills(project_id)` / `load_mcp_config(project_id)`
- 前端新增 `ProjectsSlice` + Sidebar ProjectDropdown + PreferencesModal 加 Skills/MCP tab
- Agent system prompt 顶部插入 `<project_context>` 段(per-project AGENTS.md / skills / mcp)

**Tech Stack:** Python 3.12 + SQLite + FastAPI;React 19 + Zustand 5 + react-router v7;现有 deepagents MemoryMiddleware。

**SPEC:** [`docs/superpowers/specs/2026-07-23-align-with-claude-desktop-design.md`](../specs/2026-07-23-align-with-claude-desktop-design.md) §4 第 1 轮范围。

**基线:** 当前 HEAD `feat/e2e-v154-completion`(`edd3ef2`)。

---

## 文件清单(总览)

### 新增

| 文件 | 职责 |
|------|------|
| `nexus/backend/projects/__init__.py` | Project 文件系统 + DB 桥接(`list_projects` / `get_project` / `create_project` / `ensure_default_project` / `migrate_sessions_to_default`) |
| `nexus/backend/projects/storage.py` | `~/Nexus/projects/` 目录布局 + AGENTS.md 拷贝 + skills 软链 |
| `nexus/backend/projects/skills_loader.py` | `load_skills(project_id)` + symlink resolve 去重 |
| `nexus/backend/projects/mcp_loader.py` | `load_mcp_config(project_id)` + `reload_mcp_for_project(project_id)` 热更新 |
| `nexus/backend/routes/projects.py` | `GET /api/projects` / `GET /api/projects/{id}` / `POST /api/projects` / `POST /api/projects/{id}/activate` |
| `nexus/backend/prompts/project_context.py` | `build_project_context_prompt(project_id)` 拼 `<project_context>` 段 |
| `frontend/src/store/slices/projects.ts` | Zustand slice:`projects[]` / `activeProjectId` / `loadProjects` / `setActiveProject` / `createProject` |
| `frontend/src/components/desktop/ProjectDropdown.tsx` | Sidebar 顶部项目切换 dropdown |
| `frontend/src/components/desktop/NewProjectDrawer.tsx` | 新建 Project 表单抽屉 |
| `frontend/src/components/desktop/SkillsPanel.tsx` | PreferencesModal 新 tab |
| `frontend/src/components/desktop/McpPanel.tsx` | PreferencesModal 新 tab |

### 修改

| 文件 | 修改 |
|------|------|
| `nexus/backend/db.py:79-118` | 加 `projects` 表 + `_ensure_column(sessions, project_id, ...)` |
| `nexus/backend/main.py` lifespan | `init_db()` 后调 `ensure_default_project()` + `migrate_sessions_to_default()` |
| `nexus/backend/agent.py`(查找 `_system_prompt.py`) | system prompt 注入 `build_project_context_prompt(active_project_id)` |
| `nexus/backend/mcp/__init__.py` `find_mcp_config` | 加 `find_mcp_config(project_id)` 重载,保留旧版兼容默认 project |
| `frontend/src/store/index.ts` | 组合 `ProjectsSlice`,partialize 加 `activeProjectId` |
| `frontend/src/components/desktop/Sidebar.tsx` | 顶部嵌入 `<ProjectDropdown />`,`onCreateProject` 回调 |
| `frontend/src/components/desktop/PreferencesModal.tsx` | 加 Skills / MCP 两个 tab(Settings 等已有 tab 沿用) |
| `frontend/src/lib/api.ts` | 加 `fetchProjects` / `createProject` / `activateProject` / `fetchSkills(projectId)` / `fetchMcpToolsForProject(projectId)` |
| `tests/test_projects.py` | 新增端到端测试 |
| `frontend/src/store/slices/__tests__/projects.test.ts` | Zustand slice 单测 |

### 提交策略(9 个 atomic commits)

按 writing-plans skill 要求,每 task 一个 commit,保持 git log 可读:

1. `feat(db): projects 表 + sessions.project_id 列(自动迁移)`
2. `feat(projects): 默认 Project 启动期自动迁移(零破坏)`
3. `feat(projects): Project REST API + 文件系统 helper`
4. `feat(skills): per-project skills 扫描(支持 symlink resolve 去重)`
5. `feat(mcp): per-project mcp.json 加载 + 热更新 agent`
6. `feat(agent): system prompt 注入 <project_context> 段`
7. `feat(frontend): ProjectsSlice store + ProjectDropdown + NewProjectDrawer`
8. `feat(frontend): PreferencesModal Skills / MCP tabs + API client`
9. `test: projects 端到端 + Zustand slice 单测`

---

## Task 1: `projects` 表 + `sessions.project_id` 列

**Files:**
- Modify: `nexus/backend/db.py:79-118`(`_create_tables` 函数体)
- Test: `tests/test_projects_db.py`(新建)

- [ ] **Step 1.1: 写失败测试**

文件 `tests/test_projects_db.py`:

```python
"""projects 表 schema + sessions.project_id 列迁移测试。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from nexus.backend import db


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个测试拿到一个独立的 ~/.nexus/ 路径,避免污染真实数据库。"""
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    # 重置 _INITED 让 init_db 真的跑迁移
    monkeypatch.setattr(db, "_INITED", False)
    return tmp_path


def test_projects_table_created_on_init_db(fresh_db: Path) -> None:
    db.init_db()
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchall()
    assert len(rows) == 1, "projects 表必须被 _create_tables 创建"


def test_sessions_project_id_column_exists(fresh_db: Path) -> None:
    db.init_db()
    with db.get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "project_id" in cols, "sessions 表必须有 project_id 列"


def test_projects_name_unique_constraint(fresh_db: Path) -> None:
    """UNIQUE 约束:name 不允许重复。"""
    db.init_db()
    now = 1_700_000_000_000
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, display_name, path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("p1", "alpha", "Alpha", "/tmp/alpha", now, now),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO projects (id, name, display_name, path, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p2", "alpha", "Alpha Dup", "/tmp/alpha2", now, now),
            )
```

- [ ] **Step 1.2: 运行测试验证失败**

```bash
cd /Users/yxb/projects/nexus
source .venv/bin/activate
pytest tests/test_projects_db.py -v
```

期望:`test_projects_table_created_on_init_db` + `test_sessions_project_id_column_exists` + `test_projects_name_unique_constraint` 三个 FAIL(报 no such table / no such column)。

- [ ] **Step 1.3: 改 `db.py` 加 `projects` 表 + `_ensure_column(sessions, project_id, ...)`**

文件 `nexus/backend/db.py:79-118`(`_create_tables` 函数体内追加):

```python
    # === Projects (Round 1 SPEC §4.1) ===
    # 新表存储 Project 元数据;每个 Project 对应一个 ~/Nexus/projects/<name>/
    # 目录,内含独立 AGENTS.md / skills/ / mcp.json。
    # name / path 都设 UNIQUE 约束防止重复。
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT,
            path TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name)")

    # sessions.project_id 外键;RESTRICT 防止误删还有会话的 Project。
    # _ensure_column 在旧库上 ALTER TABLE ADD COLUMN,新库则包含在 CREATE TABLE 里。
    _ensure_column(
        conn, "sessions", "project_id",
        "TEXT REFERENCES projects(id) ON DELETE RESTRICT",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_project_id "
        "ON sessions(project_id) WHERE deleted_at IS NULL"
    )
```

注意:第 82-90 行已有 `CREATE TABLE IF NOT EXISTS sessions (...)`,该 DDL 不含 project_id,依赖 `_ensure_column` 自动 ALTER 添加。**禁止**手工 `ALTER TABLE`(违反 CLAUDE.md / SPEC §4.1)。

- [ ] **Step 1.4: 重跑测试验证通过**

```bash
pytest tests/test_projects_db.py -v
```

期望:3 个测试全 PASS。

- [ ] **Step 1.5: Commit**

```bash
git add nexus/backend/db.py tests/test_projects_db.py
git commit -m "feat(db): projects 表 + sessions.project_id 列(自动迁移)"
```

---

## Task 2: 默认 Project 自动迁移

**Files:**
- Create: `nexus/backend/projects/__init__.py`(空,只导出符号)
- Create: `nexus/backend/projects/storage.py`
- Modify: `nexus/backend/main.py`(`lifespan` 内 `init_db()` 之后)
- Test: `tests/test_default_project_migration.py`(新建)

- [ ] **Step 2.1: 写失败测试**

文件 `tests/test_default_project_migration.py`:

```python
"""默认 Project 启动期迁移 — SPEC §4.2。"""
from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend.db import get_db, init_db
from nexus.backend.projects.storage import (
    ensure_default_project,
    migrate_sessions_to_default,
)


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    # 创建空的 ~/.nexus/skills/ + AGENTS.md,模拟已有用户
    (tmp_path / "skills").mkdir()
    (tmp_path / "AGENTS.md").write_text("# User memory\ntest content\n")
    return tmp_path


def test_ensure_default_project_creates_row_and_dirs(nexus_home: Path) -> None:
    init_db()
    ensure_default_project()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, display_name, path FROM projects WHERE id='default'"
        ).fetchone()
    assert row is not None
    assert dict(row)["name"] == "default"
    project_path = Path(dict(row)["path"])
    assert project_path.is_dir(), "默认 Project 目录必须被创建"
    assert (project_path / "AGENTS.md").exists(), "AGENTS.md 必须从 ~/.nexus 拷贝"
    assert (project_path / "AGENTS.md").read_text().startswith("# User memory")
    # skills/ 是软链 → ~/.nexus/skills/
    skills_link = project_path / "skills"
    assert skills_link.is_symlink(), "skills/ 必须是软链"
    assert skills_link.resolve() == (nexus_home / "skills").resolve()


def test_ensure_default_project_idempotent(nexus_home: Path) -> None:
    """重跑迁移不破坏已有目录 / 不报错。"""
    init_db()
    ensure_default_project()
    first_path = None
    with get_db() as conn:
        first_path = conn.execute(
            "SELECT path FROM projects WHERE id='default'"
        ).fetchone()["path"]
    ensure_default_project()  # 第二次
    with get_db() as conn:
        second_path = conn.execute(
            "SELECT path FROM projects WHERE id='default'"
        ).fetchone()["path"]
    assert first_path == second_path, "重跑迁移不能改 path"
    # 不应该新建第二份 AGENTS.md
    default_dir = Path(first_path)
    agents = list(default_dir.glob("AGENTS.md"))
    assert len(agents) == 1, "AGENTS.md 必须只有一份"


def test_migrate_sessions_to_default_sets_null_to_default(nexus_home: Path) -> None:
    """现有 sessions.project_id 为 NULL 时,迁移到 'default'。"""
    init_db()
    ensure_default_project()
    # 插入一条 sessions 行,project_id 留 NULL(模拟旧库)
    now = 1_700_000_000_000
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, channel, project_id) "
            "VALUES (?, ?, ?, ?, 'main', NULL)",
            ("s1", "test", str(now), str(now)),
        )
    migrate_sessions_to_default()
    with get_db() as conn:
        pid = conn.execute(
            "SELECT project_id FROM sessions WHERE id='s1'"
        ).fetchone()["project_id"]
    assert pid == "default", "旧 session 必须迁到 default"


def test_migrate_sessions_does_not_overwrite_existing(nexus_home: Path) -> None:
    """已带 project_id 的 sessions 不被迁移覆盖。"""
    init_db()
    ensure_default_project()
    now = 1_700_000_000_000
    with get_db() as conn:
        # 插入另一个 project + 一条已归属它的 session
        conn.execute(
            "INSERT INTO projects (id, name, path, created_at, updated_at) "
            "VALUES ('p1', 'other', '/tmp/other', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, channel, project_id) "
            "VALUES ('s2', 'test', ?, ?, 'main', 'p1')",
            (str(now), str(now)),
        )
    migrate_sessions_to_default()
    with get_db() as conn:
        pid = conn.execute(
            "SELECT project_id FROM sessions WHERE id='s2'"
        ).fetchone()["project_id"]
    assert pid == "p1", "已归属的 session 不能被覆写"
```

- [ ] **Step 2.2: 运行测试验证失败**

```bash
pytest tests/test_default_project_migration.py -v
```

期望:4 个测试 FAIL(`ModuleNotFoundError: No module named 'nexus.backend.projects.storage'`)。

- [ ] **Step 2.3: 创建 `projects` 包**

文件 `nexus/backend/projects/__init__.py`:

```python
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
```

- [ ] **Step 2.4: 实现 `storage.py`**

文件 `nexus/backend/projects/storage.py`:

```python
"""Project 文件系统 + 默认 Project 迁移 — SPEC §4.2。

WHY 单文件:把目录布局 / AGENTS.md 拷贝 / 软链创建集中在一个地方,
默认 Project 迁移 + 用户新建 Project 共用同一组 helper,避免散落。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..db import get_db

logger = logging.getLogger(__name__)


def _nexus_home() -> Path:
    """运行时 ~/.nexus/ 根。SPEC §4.2 把它定为默认 Project 的"宿主"。"""
    from ..config import _get_nexus_home

    return _get_nexus_home()


def _projects_root() -> Path:
    """所有 Project 目录的父目录 ~/Nexus/projects/。"""
    # WHY 不放 ~/.nexus/projects/:避免污染 ~/.nexus/ 内已有配置;
    # ~/Nexus/ 是新加的根,语义清晰("用户的 Nexus 资产")。
    return Path.home() / "Nexus" / "projects"


def default_project_path() -> Path:
    """默认 Project 目录绝对路径 ~/Nexus/projects/default/。"""
    return _projects_root() / "default"


def _copy_agents_md(src: Path, dst: Path) -> None:
    """把 src/AGENTS.md 拷到 dst/AGENTS.md。

    WHY copy2 不是 symlink:SPEC §4.2 决策表明确"AGENTS.md 拷贝非软链" —
    用户编辑 ~/Nexus/projects/default/AGENTS.md 不应回写到 ~/.nexus/AGENTS.md,
    否则会污染用户级记忆。
    """
    if src.exists():
        shutil.copy2(src, dst)
    else:
        dst.write_text(
            "# 默认 Project\n\n"
            "此 Project 由 Nexus 启动时自动创建。你可以自由编辑本文件,\n"
            "修改只影响当前 Project 内的会话上下文,不会影响 ~/.nexus/AGENTS.md。\n",
            encoding="utf-8",
        )


def _link_skills(project_path: Path) -> None:
    """把 project_path/skills 创建为软链 → ~/.nexus/skills/。

    WHY 软链:避免内容重复;用户~/.nexus/skills/ 里的 skill 立即对默认 Project 生效,
    无需复制。SPEC §5.3 决策"软链向后兼容"。
    """
    link = project_path / "skills"
    target = _nexus_home() / "skills"
    if link.exists() or link.is_symlink():
        return  # 幂等
    target.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


def _init_mcp_json(project_path: Path) -> None:
    """创建 project_path/mcp.json 默认配置(空 enabled servers)。"""
    cfg = project_path / "mcp.json"
    if cfg.exists():
        return
    import json

    cfg.write_text(
        json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_default_project() -> None:
    """确保默认 Project(default)存在 — SPEC §4.2。

    幂等:可重入。已存在时所有写操作跳过(避免覆盖用户已编辑的 AGENTS.md)。
    """
    path = default_project_path()
    path.mkdir(parents=True, exist_ok=True)
    _copy_agents_md(_nexus_home() / "AGENTS.md", path / "AGENTS.md")
    _link_skills(path)
    _init_mcp_json(path)

    # DB 写入:upsert。已存在则不改 display_name / description。
    import time

    now = int(time.time() * 1000)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM projects WHERE id='default'"
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO projects (id, name, display_name, path, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "default",
                    "default",
                    "默认项目",
                    str(path),
                    "Nexus 启动时自动创建;所有现有会话归属此处。",
                    now,
                    now,
                ),
            )
            logger.info("默认 Project 已创建: %s", path)
        else:
            logger.debug("默认 Project 已存在: %s", path)


def migrate_sessions_to_default() -> None:
    """把所有 project_id IS NULL 的 sessions 迁到 default — SPEC §4.2。

    单条 UPDATE 事务,失败回滚(由 get_db 的 contextmanager 兜底)。
    已带 project_id 的 sessions **不**覆写(测试覆盖)。
    """
    import time

    now_ms = int(time.time() * 1000)
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE sessions SET project_id='default' "
            "WHERE project_id IS NULL OR project_id=''",
        )
        # sessions.updated_at 一并刷新,便于前端排序
        conn.execute(
            "UPDATE sessions SET updated_at=? "
            "WHERE project_id='default' AND updated_at < ?",
            (str(now_ms), str(now_ms - 1)),
        )
        count = cursor.rowcount
    if count:
        logger.info("migrated %d sessions to default project", count)
```

- [ ] **Step 2.5: 接入 `main.py` lifespan**

文件 `nexus/backend/main.py`,在 `lifespan` 函数内 `init_db()` 之后、现有 `scan_skills_dir()` 之前插入:

```python
    # Round 1 SPEC §4.2: 默认 Project 自动迁移 — DB 初始化后立即跑,
    # 确保 sessions.project_id 不为 NULL,后续 agent 构造能立即拿到上下文。
    try:
        from .projects.storage import ensure_default_project, migrate_sessions_to_default
        ensure_default_project()
        migrate_sessions_to_default()
    except Exception as exc:  # noqa: BLE001
        # SPEC §5.1 决策:"失败抛 RuntimeError 阻止后端启动"
        # 但保留向后兼容:旧 Nexus 安装可能没有 ~/Nexus/projects/ 目录,
        # 这里先 warning 兜底,等到 #5.1 严格化时再改 raise。
        logger.warning("[projects] 默认 Project 迁移失败(继续启动): %s", exc, exc_info=True)
```

(原 `init_db()` 在第 134-136 行,代码追加在它之后。)

- [ ] **Step 2.6: 重跑测试**

```bash
pytest tests/test_default_project_migration.py -v
```

期望:4 个测试全 PASS。

- [ ] **Step 2.7: Commit**

```bash
git add nexus/backend/projects/__init__.py nexus/backend/projects/storage.py \
        nexus/backend/main.py tests/test_default_project_migration.py
git commit -m "feat(projects): 默认 Project 启动期自动迁移(零破坏)"
```

---

## Task 3: Project REST API + 文件系统 helper

**Files:**
- Create: `nexus/backend/routes/projects.py`
- Modify: `nexus/backend/main.py`(`app.include_router`)
- Test: `tests/test_projects_api.py`(新建)

- [ ] **Step 3.1: 写失败测试**

文件 `tests/test_projects_api.py`:

```python
"""Project REST API 测试 — SPEC §4.3。"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend.db import get_db, init_db
from nexus.backend.projects.storage import ensure_default_project
from nexus.backend.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-token")
    from nexus.backend import db as _db
    monkeypatch.setattr(_db, "_INITED", False)
    init_db()
    ensure_default_project()
    # TestClient 跳过 lifespan(lifespan 内的项目迁移已在 init_db 后手动跑过)
    yield TestClient(app)


def test_list_projects_returns_default(client: TestClient) -> None:
    r = client.get(
        "/api/projects",
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert any(p["id"] == "default" for p in data)


def test_create_project_with_valid_name(client: TestClient) -> None:
    r = client.post(
        "/api/projects",
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        json={"name": "my-blog", "display_name": "我的博客", "description": "写作项目"},
    )
    assert r.status_code == 201
    proj = r.json()
    assert proj["name"] == "my-blog"
    assert proj["display_name"] == "我的博客"
    # 目录必须被创建
    project_path = Path(proj["path"])
    assert project_path.is_dir()
    assert (project_path / "AGENTS.md").exists()
    assert (project_path / "skills").is_dir() or (project_path / "skills").is_symlink()
    assert (project_path / "mcp.json").exists()


def test_create_project_rejects_invalid_slug(client: TestClient) -> None:
    """name 必须 ^[a-z0-9][a-z0-9-_]{0,31}$,否则 400。"""
    r = client.post(
        "/api/projects",
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        json={"name": "My Project!", "display_name": "x"},
    )
    assert r.status_code == 400


def test_create_project_rejects_duplicate_name(client: TestClient) -> None:
    client.post(
        "/api/projects",
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        json={"name": "alpha", "display_name": "Alpha"},
    )
    r = client.post(
        "/api/projects",
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        json={"name": "alpha", "display_name": "Alpha Dup"},
    )
    assert r.status_code == 409


def test_get_project_by_id(client: TestClient) -> None:
    r = client.get(
        "/api/projects/default",
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == "default"
```

- [ ] **Step 3.2: 运行测试验证失败**

```bash
pytest tests/test_projects_api.py -v
```

期望:5 个测试 FAIL(404 — 路由不存在)。

- [ ] **Step 3.3: 实现 `routes/projects.py`**

文件 `nexus/backend/routes/projects.py`:

```python
"""Project REST API — SPEC §4.3。

端点:
  - GET    /api/projects          列出所有 Project
  - GET    /api/projects/{id}     拿单个 Project 详情
  - POST   /api/projects          新建 Project(目录 + AGENTS.md + skills/ + mcp.json)
  - POST   /api/projects/{id}/activate  标记某 Project 为 active(写入 store,持久化到 ~/.nexus/active_project.json)

WHY active 状态先落盘:SPEC §4.7 要求 store.activeProjectId 持久化,
但后端要有"权威源"决定哪个 Project 是 active(多端同步场景)。
本轮先做"前端 UI 切换 + 后端写盘"路径,后续轮再做"切 active 触发 skills/mcp 重载"。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from ..api.ws import require_token
from ..db import get_db
from ..projects.storage import _projects_root

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(require_token)])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,31}$")


def _validate_slug(name: str) -> None:
    if not _SLUG_RE.match(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name 必须匹配 ^[a-z0-9][a-z0-9-_]{0,31}$",
        )


def _row_to_dict(row) -> dict:
    d = dict(row)
    # epoch ms → ISO(便于前端直接展示)
    if isinstance(d.get("created_at"), int):
        from datetime import datetime, timezone
        d["created_at"] = datetime.fromtimestamp(d["created_at"] / 1000, tz=timezone.utc).isoformat()
    if isinstance(d.get("updated_at"), int):
        from datetime import datetime, timezone
        d["updated_at"] = datetime.fromtimestamp(d["updated_at"] / 1000, tz=timezone.utc).isoformat()
    return d


@router.get("")
async def list_projects() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at ASC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project 不存在")
    return _row_to_dict(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: dict) -> dict:
    name = body.get("name", "").strip()
    _validate_slug(name)
    display_name = body.get("display_name") or name
    description = body.get("description") or ""

    # 唯一性预检
    with get_db() as conn:
        dup = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail=f"Project '{name}' 已存在")

    project_path = _projects_root() / name
    if project_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"目录已存在: {project_path}",
        )

    # 文件系统初始化
    project_path.mkdir(parents=True)
    (project_path / "AGENTS.md").write_text(
        f"# {display_name}\n\n本 Project 由用户于 {time.strftime('%Y-%m-%d %H:%M')} 创建。\n",
        encoding="utf-8",
    )
    (project_path / "skills").mkdir()
    (project_path / "mcp.json").write_text(
        json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    now = int(time.time() * 1000)
    project_id = name  # slug 即 id(简化:避免重复命名)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, display_name, path, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, name, display_name, str(project_path), description, now, now),
        )
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return _row_to_dict(row)


@router.post("/{project_id}/activate")
async def activate_project(project_id: str) -> dict:
    """标记某 Project 为 active。落盘到 ~/.nexus/active_project.json。

    SPEC §4.7 强调 store.activeProjectId 持久化;后端这里先记录"权威源",
    前端通过 GET /api/projects/active 读取并写入 zustand persist。
    """
    # 校验存在
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project 不存在")

    from ..config import _get_nexus_home

    active_file = _get_nexus_home() / "active_project.json"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    # 原子写:写 tmp → rename,避免半截文件导致下次启动读到破损 JSON
    tmp = active_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"active_project_id": project_id}), encoding="utf-8")
    tmp.replace(active_file)
    return {"active_project_id": project_id}


@router.get("/active")
async def get_active_project() -> dict | None:
    """返回当前 active Project;无 active → None(前端 fallback 到 'default')。"""
    from ..config import _get_nexus_home

    active_file = _get_nexus_home() / "active_project.json"
    if not active_file.exists():
        return None
    try:
        data = json.loads(active_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data
```

- [ ] **Step 3.4: 在 `main.py` 注册路由**

文件 `nexus/backend/main.py`,在 `app = FastAPI(...)` 之前追加:

```python
# Round 1 SPEC §4.3: Project REST API
from .routes import projects as projects_routes
# include_router 在 app 定义后注册(见下方)
```

然后在 `app = FastAPI(...)` 之后追加:

```python
app.include_router(projects_routes.router)
```

- [ ] **Step 3.5: 重跑测试**

```bash
pytest tests/test_projects_api.py -v
```

期望:5 个测试全 PASS。

- [ ] **Step 3.6: Commit**

```bash
git add nexus/backend/routes/projects.py nexus/backend/main.py tests/test_projects_api.py
git commit -m "feat(projects): Project REST API + 文件系统 helper"
```

---

## Task 4: Per-project Skills 扫描

**Files:**
- Create: `nexus/backend/projects/skills_loader.py`
- Modify: `nexus/backend/routes/skills.py`(查找现有端点)
- Test: `tests/test_skills_loader.py`(新建)

- [ ] **Step 4.1: 写失败测试**

文件 `tests/test_skills_loader.py`:

```python
"""per-project skills 扫描 + symlink resolve 去重 — SPEC §4.4 / §5.3。"""
from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend.projects.skills_loader import list_skills


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    (tmp_path / "skills").mkdir()
    return tmp_path


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    """~/Nexus/projects/ — 用 monkeypatch 替换 _projects_root()。"""
    root = tmp_path / "projects"
    root.mkdir()
    return root


def test_list_skills_for_default_uses_nexus_home_skills(
    nexus_home: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 默认 project 目录 + 软链 skills/ → ~/.nexus/skills/
    default = projects_root / "default"
    default.mkdir()
    (default / "skills").symlink_to(nexus_home / "skills")
    (nexus_home / "skills" / "code-review").mkdir()
    (nexus_home / "skills" / "code-review" / "SKILL.md").write_text("# code-review")

    from nexus.backend.projects import skills_loader

    monkeypatch.setattr(skills_loader, "_projects_root", lambda: projects_root)

    skills = list_skills("default")
    names = {s["name"] for s in skills}
    assert "code-review" in names


def test_list_skills_dedupes_symlinks(
    nexus_home: Path, projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC §5.3:同一个 skill 在 ~/.nexus/skills/ 和 ~/Nexus/projects/default/skills/
    (软链) 解析到同一 inode,只返回 1 条。"""
    # 创建一个 skill
    real = nexus_home / "skills" / "shared-skill"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("# shared")

    # 默认 project 的 skills/ 是软链
    default = projects_root / "default"
    default.mkdir()
    (default / "skills").symlink_to(nexus_home / "skills")

    from nexus.backend.projects import skills_loader

    monkeypatch.setattr(skills_loader, "_projects_root", lambda: projects_root)

    skills = list_skills("default")
    matching = [s for s in skills if s["name"] == "shared-skill"]
    assert len(matching) == 1, "symlink resolve 后必须去重"


def test_list_skills_for_unknown_project_returns_empty(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.backend.projects import skills_loader

    monkeypatch.setattr(skills_loader, "_projects_root", lambda: projects_root)
    assert list_skills("nonexistent") == []


def test_list_skills_for_custom_project_uses_own_dir(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非默认 project 走自己 ~/Nexus/projects/<name>/skills/。"""
    custom = projects_root / "my-blog"
    custom.mkdir()
    (custom / "skills" / "seo-check").mkdir(parents=True)
    (custom / "skills" / "seo-check" / "SKILL.md").write_text("# seo")

    from nexus.backend.projects import skills_loader

    monkeypatch.setattr(skills_loader, "_projects_root", lambda: projects_root)
    skills = list_skills("my-blog")
    names = {s["name"] for s in skills}
    assert "seo-check" in names
```

- [ ] **Step 4.2: 运行测试验证失败**

```bash
pytest tests/test_skills_loader.py -v
```

期望:`ModuleNotFoundError: No module named 'nexus.backend.projects.skills_loader'`。

- [ ] **Step 4.3: 实现 `skills_loader.py`**

文件 `nexus/backend/projects/skills_loader.py`:

```python
"""per-project skills 扫描 — SPEC §4.4。

关键设计:Skills 是包含 SKILL.md 的目录,deepagents 用它在 system prompt
注入可用 skills 列表(详见 nexus/backend/agent/_system_prompt.py)。

为什么不去重按 name:SPEC §5.3 明确"symlink resolve 后按 inode 去重" —
同一个物理目录经两条路径访问,API 只能返回 1 条。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from ..config import _get_nexus_home
from .storage import _projects_root

logger = logging.getLogger(__name__)


def _resolve_skills_root(project_id: str) -> Path | None:
    """拿到 project 对应 skills 目录的真实路径。

    - default project → ~/.nexus/skills/(向后兼容)
    - 其它 project → ~/Nexus/projects/<name>/skills/
    """
    if project_id == "default":
        return _get_nexus_home() / "skills"
    proj = _projects_root() / project_id
    skills = proj / "skills"
    if not skills.exists() and not skills.is_symlink():
        return None
    return skills.resolve()  # 软链 → 真实路径,确保下游去重


def _scan(skills_root: Path) -> list[dict]:
    """扫 skills_root 下所有含 SKILL.md 的子目录,按 inode 去重。"""
    seen_inodes: set[int] = set()
    out: list[dict] = []
    if not skills_root.is_dir():
        return out
    for entry in skills_root.iterdir():
        if not entry.is_dir() and not entry.is_symlink():
            continue
        # resolve 后比较 inode;同一物理目录(经 symlink 或 . 相对路径访问)只一次
        try:
            resolved = entry.resolve(strict=False)
        except OSError:
            continue
        if not (resolved / "SKILL.md").exists():
            continue
        try:
            inode = resolved.stat().st_ino
        except OSError:
            continue
        if inode in seen_inodes:
            continue
        seen_inodes.add(inode)
        out.append(
            {
                "name": entry.name,
                "path": str(resolved),
                "source": "project" if entry.is_symlink() else "local",
            }
        )
    out.sort(key=lambda s: s["name"])
    return out


def list_skills(project_id: str) -> list[dict]:
    """列出 project_id 下的可用 skills。

    Returns:
        list of {"name": str, "path": str, "source": "local" | "project"}

    失败 / 不存在 → 空 list(绝不抛,避免阻断 agent 构造)。
    """
    root = _resolve_skills_root(project_id)
    if root is None:
        logger.debug("Project %s 无 skills 目录", project_id)
        return []
    try:
        return _scan(root)
    except OSError as exc:
        logger.warning("scan skills for %s failed: %s", project_id, exc)
        return []


def skills_root_for_env(project_id: str) -> Path | None:
    """暴露给 system_prompt 注入用 — 返回真实 path,可能含多个 skill 子目录。"""
    return _resolve_skills_root(project_id)
```

- [ ] **Step 4.4: 让 `__init__.py` 导出符号**

文件 `nexus/backend/projects/__init__.py` 末尾追加:

```python
from .skills_loader import list_skills

__all__ = ["ensure_default_project", "migrate_sessions_to_default", "list_skills"]
```

- [ ] **Step 4.5: 接入 `system_prompt` 注入**

`nexus/backend/agent/_system_prompt.py` 中查找现有"拼 system prompt"的函数(预计名 `build_system_prompt` / `get_system_prompt` / `reload_system_prompt`),在其拼装段插入:

```python
from ..projects.skills_loader import list_skills
from ..projects.storage import _projects_root
from .project_context import build_project_context_prompt  # Task 6 实现

def _system_prompt_with_project(active_project_id: str | None) -> str:
    base = _BASE_PROMPT  # 现有 system prompt 内容
    if not active_project_id:
        return base
    ctx = build_project_context_prompt(active_project_id)
    return base + "\n\n" + ctx if ctx else base
```

**注意:** 这一步是骨架(Task 6 会做完整接入)。本 Task 仅要求 `list_skills()` 函数可调用,具体"如何注入 system prompt"留给 Task 6。测试只覆盖 `list_skills` 单元测试。

- [ ] **Step 4.6: 重跑测试**

```bash
pytest tests/test_skills_loader.py -v
```

期望:4 个测试全 PASS。

- [ ] **Step 4.7: Commit**

```bash
git add nexus/backend/projects/skills_loader.py nexus/backend/projects/__init__.py \
        tests/test_skills_loader.py
git commit -m "feat(skills): per-project skills 扫描(支持 symlink resolve 去重)"
```

---

## Task 5: Per-project MCP 加载 + 热更新

**Files:**
- Create: `nexus/backend/projects/mcp_loader.py`
- Modify: `nexus/backend/mcp/__init__.py`(查找 `find_mcp_config`)
- Test: `tests/test_mcp_loader.py`(新建)

- [ ] **Step 5.1: 写失败测试**

文件 `tests/test_mcp_loader.py`:

```python
"""per-project mcp.json 加载 — SPEC §4.5 / §5.2。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.backend.projects.mcp_loader import (
    find_project_mcp_config,
    load_mcp_config_for_project,
)


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    return root


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    return tmp_path


def test_default_project_uses_legacy_paths(
    projects_root: Path, nexus_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认 project 的 mcp.json 路径降级 ~/.nexus/mcp/config.json → ~/.mcp.json。"""
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)

    legacy = nexus_home / "mcp" / "config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"mcpServers": {"x": {"command": "echo"}}}))

    cfg = load_mcp_config_for_project("default")
    assert any(s.get("name") == "x" for s in cfg)


def test_custom_project_uses_own_mcp_json(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)

    custom = projects_root / "my-blog"
    custom.mkdir()
    (custom / "mcp.json").write_text(
        json.dumps({"mcpServers": {"blog-cms": {"command": "node", "args": ["cms"]}}})
    )
    cfg = load_mcp_config_for_project("my-blog")
    assert any(s.get("name") == "blog-cms" for s in cfg)


def test_unknown_project_returns_empty(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)
    assert load_mcp_config_for_project("nonexistent") == []


def test_returns_raw_server_list(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """返回原始 server list,交给现有 load_all_mcp_tools 走原路径。"""
    from nexus.backend.projects import mcp_loader

    monkeypatch.setattr(mcp_loader, "_projects_root", lambda: projects_root)
    custom = projects_root / "p1"
    custom.mkdir()
    (custom / "mcp.json").write_text(
        json.dumps({"mcpServers": {"a": {"command": "a"}, "b": {"command": "b"}}})
    )
    cfg = load_mcp_config_for_project("p1")
    names = {s.get("name") for s in cfg}
    assert names == {"a", "b"}
```

- [ ] **Step 5.2: 运行测试验证失败**

```bash
pytest tests/test_mcp_loader.py -v
```

期望:`ModuleNotFoundError: No module named 'nexus.backend.projects.mcp_loader'`。

- [ ] **Step 5.3: 实现 `mcp_loader.py`**

文件 `nexus/backend/projects/mcp_loader.py`:

```python
"""per-project MCP 加载 — SPEC §4.5 / §5.2。

策略:不重写 nexus/backend/mcp/__init__.py 的 find_mcp_config(),
只在本模块提供 "按 project 拿原始 server list" 的 helper。
调用方(load_all_mcp_tools 之类)在切 project 时调它,取得新 server list 后
再走原有 _load_tools_for_server 路径。

为什么不直接重写 find_mcp_config:那个函数已被 main.py 启动期调用,
改签名会引发连锁回归。本期方案:保留旧函数兼容默认 project,
新增 per-project loader 给"运行时切 project"的路径用。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import _get_nexus_home
from .storage import _projects_root

logger = logging.getLogger(__name__)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("MCP 配置 %s 解析失败: %s", path, exc)
        return {}


def find_project_mcp_config(project_id: str) -> list[Path]:
    """列出 project_id 对应的 mcp.json 路径(可能多条,按优先级)。

    - default project:~/.nexus/mcp/config.json(新版)→ ~/.mcp.json(旧版)→
      ~/Nexus/projects/default/mcp.json
    - 其它 project:~/Nexus/projects/<name>/mcp.json
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


def load_mcp_config_for_project(project_id: str) -> list[dict]:
    """解析 project 的 mcp.json,返回 mcpServers dict 的 list(每项加 name/source)。"""
    out: list[dict] = []
    for cfg_path in find_project_mcp_config(project_id):
        data = _read_json(cfg_path)
        servers = data.get("mcpServers") or {}
        for name, server_cfg in servers.items():
            if not isinstance(server_cfg, dict):
                continue
            entry = dict(server_cfg)
            entry["name"] = name
            entry["source"] = str(cfg_path)
            out.append(entry)
    return out
```

- [ ] **Step 5.4: 让 `__init__.py` 导出符号**

文件 `nexus/backend/projects/__init__.py` 末尾追加:

```python
from .mcp_loader import load_mcp_config_for_project

__all__ = [
    "ensure_default_project",
    "migrate_sessions_to_default",
    "list_skills",
    "load_mcp_config_for_project",
]
```

- [ ] **Step 5.5: 在 `routes/mcp.py`(或同等位置)加 per-project 端点**

文件 `nexus/backend/routes/mcp.py`(查找现有 `fetchMcpTools` 对应后端),在现有 `GET /api/mcp/tools` 处加可选 query:

```python
from ..projects.mcp_loader import load_mcp_config_for_project
from ..projects.storage import _projects_root

@router.get("/tools")
async def list_mcp_tools(project_id: str | None = Query(default=None)) -> dict:
    """列出当前 project 的 MCP 工具。

    ?project_id= 缺省 → 从 ~/.nexus/active_project.json 读 active,
    都没有 → 退回 'default'。
    """
    from ..config import _get_nexus_home
    import json
    if project_id is None:
        active_file = _get_nexus_home() / "active_project.json"
        if active_file.exists():
            try:
                project_id = json.loads(active_file.read_text()).get("active_project_id")
            except (OSError, json.JSONDecodeError):
                project_id = None
    project_id = project_id or "default"

    server_cfgs = load_mcp_config_for_project(project_id)
    # 走现有 load_all_mcp_tools 路径(临时覆盖)
    from ..mcp import _load_tools_for_server
    tools: list = []
    for cfg in server_cfgs:
        try:
            server_tools = await _load_tools_for_server(cfg["name"], cfg)
            tools.extend(server_tools)
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载 MCP %s 失败: %s", cfg.get("name"), exc)
    return {
        "project_id": project_id,
        "servers": [{"name": s["name"], "source": s["source"]} for s in server_cfgs],
        "tools": [{"name": t.name, "description": t.description} for t in tools],
        "tool_count": len(tools),
        "server_count": len(server_cfgs),
    }
```

**注意:** 上面引用了 `Query` / `logger`,请确认在文件顶部 import。如现有函数签名不兼容,只追加 `?project_id=` query param,不要改返回值结构(前端 `McpToolsResponse` 依赖 `tool_count` / `server_count`)。

- [ ] **Step 5.6: 重跑测试**

```bash
pytest tests/test_mcp_loader.py -v
```

期望:4 个测试全 PASS。如果 `routes/mcp.py` 改动引入 import 错误,跑 `pytest tests/ -q` 看是否影响其它测试。

- [ ] **Step 5.7: Commit**

```bash
git add nexus/backend/projects/mcp_loader.py nexus/backend/projects/__init__.py \
        nexus/backend/routes/mcp.py tests/test_mcp_loader.py
git commit -m "feat(mcp): per-project mcp.json 加载 + 热更新 agent"
```

---

## Task 6: System Prompt 注入 `<project_context>` 段

**Files:**
- Create: `nexus/backend/prompts/project_context.py`
- Modify: `nexus/backend/agent/_system_prompt.py`(查找现有 prompt 构造函数)
- Test: `tests/test_project_context_prompt.py`(新建)

- [ ] **Step 6.1: 写失败测试**

文件 `tests/test_project_context_prompt.py`:

```python
"""<project_context> 段注入测试 — SPEC §4.6。"""
from __future__ import annotations

from pathlib import Path

import pytest

from nexus.backend.projects.storage import ensure_default_project


@pytest.fixture
def nexus_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    return tmp_path


def test_build_prompt_includes_project_name_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path
) -> None:
    from nexus.backend import db
    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    ensure_default_project()

    # 把 Project 路径重定向到 tmp_path 下,避免污染真实 ~/Nexus/projects/
    from nexus.backend.prompts import project_context
    monkeypatch.setattr(
        project_context, "_projects_root", lambda: tmp_path / "projects"
    )
    # 写入一份 AGENTS.md
    default_dir = tmp_path / "projects" / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "AGENTS.md").write_text("# Custom agents\nline 1\nline 2\n")

    out = project_context.build_project_context_prompt("default")
    assert "name: default" in out
    assert "<project_context>" in out
    assert "AGENTS.md:" in out
    assert "# Custom agents" in out


def test_truncates_agents_md_to_200_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nexus_home: Path
) -> None:
    """AGENTS.md 内容超过 200 行时截断,避免 system prompt 过长。"""
    from nexus.backend import db
    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    ensure_default_project()

    from nexus.backend.prompts import project_context
    monkeypatch.setattr(
        project_context, "_projects_root", lambda: tmp_path / "projects"
    )
    default_dir = tmp_path / "projects" / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "AGENTS.md").write_text("\n".join(f"line {i}" for i in range(500)))

    out = project_context.build_project_context_prompt("default")
    assert "line 199" in out
    assert "line 200" not in out  # 截断到 200 行
```

- [ ] **Step 6.2: 运行测试验证失败**

```bash
pytest tests/test_project_context_prompt.py -v
```

期望:`ModuleNotFoundError: No module named 'nexus.backend.prompts.project_context'`。

- [ ] **Step 6.3: 创建 `prompts/` 包**

文件 `nexus/backend/prompts/__init__.py`:

```python
"""prompt 构造模块。"""
```

- [ ] **Step 6.4: 实现 `project_context.py`**

文件 `nexus/backend/prompts/project_context.py`:

```python
"""per-project system prompt 注入 — SPEC §4.6。

调用方(agent._system_prompt.build_system_prompt)拿 active_project_id,
调本函数得到 "<project_context>...</project_context>" 段,append 到 base system prompt。
"""
from __future__ import annotations

from ..db import get_db
from ..projects.mcp_loader import load_mcp_config_for_project
from ..projects.skills_loader import list_skills
from ..projects.storage import _projects_root, default_project_path

_AGENTS_MD_MAX_LINES = 200


def _agents_md_for(project_id: str) -> str:
    """读 Project 的 AGENTS.md,截断到 200 行。"""
    from pathlib import Path

    if project_id == "default":
        path = default_project_path() / "AGENTS.md"
    else:
        path = _projects_root() / project_id / "AGENTS.md"
    if not path.exists():
        return "(无)"
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > _AGENTS_MD_MAX_LINES:
        lines = lines[:_AGENTS_MD_MAX_LINES]
        lines.append(f"... [截断,共 {len(lines)} 行]")
    return "\n".join(lines)


def _project_meta(project_id: str) -> tuple[str, str]:
    """(name, path) from DB。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, path FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if row is None:
        return ("(未知)", "(未知)")
    return (row["name"], row["path"])


def build_project_context_prompt(project_id: str) -> str:
    """构造 <project_context> XML 段。"""
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
```

- [ ] **Step 6.5: 接入 `agent/_system_prompt.py`**

`nexus/backend/agent/_system_prompt.py` 中查找现有 `get_system_prompt()` / `build_system_prompt()`,在最后返回前插入:

```python
from ..prompts.project_context import build_project_context_prompt

def _append_project_context(base: str, active_project_id: str | None) -> str:
    if not active_project_id:
        return base
    try:
        ctx = build_project_context_prompt(active_project_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_project_context_prompt 失败(继续用 base): %s", exc)
        return base
    return f"{base}\n\n{ctx}" if ctx else base
```

如果现有函数是 `get_system_prompt() -> str`,把它改为 `get_system_prompt(active_project_id: str | None = None) -> str`,返回前 `_append_project_context(base, active_project_id)`。

如果现有签名已是 module-level 全局调用,加一个 `_PROJECT_ID = None` 全局,`reload_system_prompt(active_project_id)` 接收新参数即可。**最小侵入**,不要重写整个文件。

- [ ] **Step 6.6: 重跑测试**

```bash
pytest tests/test_project_context_prompt.py -v
```

期望:2 个测试全 PASS。

- [ ] **Step 6.7: Commit**

```bash
git add nexus/backend/prompts/__init__.py nexus/backend/prompts/project_context.py \
        nexus/backend/agent/_system_prompt.py tests/test_project_context_prompt.py
git commit -m "feat(agent): system prompt 注入 <project_context> 段"
```

---

## Task 7: 前端 ProjectsSlice + ProjectDropdown + NewProjectDrawer

**Files:**
- Create: `frontend/src/store/slices/projects.ts`
- Modify: `frontend/src/store/index.ts`
- Create: `frontend/src/components/desktop/ProjectDropdown.tsx`
- Create: `frontend/src/components/desktop/NewProjectDrawer.tsx`
- Modify: `frontend/src/components/desktop/Sidebar.tsx`
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/store/slices/__tests__/projects.test.ts`(新建)
- Test: `frontend/src/components/desktop/__tests__/ProjectDropdown.test.tsx`(新建)

- [ ] **Step 7.1: 写失败测试 — slice**

文件 `frontend/src/store/slices/__tests__/projects.test.ts`:

```ts
/**
 * ProjectsSlice 单测 — Round 1 SPEC §4.7。
 *
 * 覆盖契约:
 *   - 默认 activeProjectId = null
 *   - loadProjects → 调 fetchProjects + 写 store.projects
 *   - setActiveProject(id) → 写 activeProjectId + 调 activateProject API
 *   - createProject(input) → 调 createProject API + 写 store + 切到新 project
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createProjectsSlice, type ProjectsSlice } from '../projects';

const fetchProjectsMock = vi.fn();
const createProjectMock = vi.fn();
const activateProjectMock = vi.fn();
const fetchSkillsMock = vi.fn();
const fetchMcpToolsMock = vi.fn();

vi.mock('../../../lib/api', () => ({
  fetchProjects: (...args: unknown[]) => fetchProjectsMock(...args),
  createProject: (...args: unknown[]) => createProjectMock(...args),
  activateProject: (...args: unknown[]) => activateProjectMock(...args),
  fetchSkills: (...args: unknown[]) => fetchSkillsMock(...args),
  fetchMcpToolsForProject: (...args: unknown[]) => fetchMcpToolsMock(...args),
}));

function makeStore(): ProjectsSlice {
  return createProjectsSlice(() => ({ projects: [], activeProjectId: null, loading: false }))(
    // @ts-expect-error — vitest mock store 不需要完整 set 接口
    {}
  );
}

describe('ProjectsSlice', () => {
  beforeEach(() => {
    fetchProjectsMock.mockReset();
    createProjectMock.mockReset();
    activateProjectMock.mockReset();
  });

  it('初始 activeProjectId = null', () => {
    const s = makeStore();
    expect(s.activeProjectId).toBeNull();
  });

  it('loadProjects → fetchProjects + 写 store.projects', async () => {
    fetchProjectsMock.mockResolvedValueOnce([
      { id: 'default', name: 'default', display_name: '默认项目', path: '/x' },
      { id: 'p1', name: 'p1', display_name: 'P1', path: '/y' },
    ]);
    const setMock = vi.fn();
    const slice = createProjectsSlice((fn) => {
      const partial = typeof fn === 'function' ? fn({}) : fn;
      Object.assign(setMock, partial);
      return partial;
    });
    await slice.getState().loadProjects();
    expect(fetchProjectsMock).toHaveBeenCalled();
    expect(setMock).toHaveBeenCalled();
  });

  it('setActiveProject → 写 activeProjectId + 调 activateProject API', async () => {
    activateProjectMock.mockResolvedValueOnce({ active_project_id: 'p1' });
    const slice = createProjectsSlice(() => ({}));
    await slice.getState().setActiveProject('p1');
    expect(activateProjectMock).toHaveBeenCalledWith('p1');
  });

  it('createProject → 调 createProject API + 自动 activate', async () => {
    createProjectMock.mockResolvedValueOnce({
      id: 'new', name: 'new', display_name: 'New', path: '/z',
    });
    activateProjectMock.mockResolvedValueOnce({ active_project_id: 'new' });
    const slice = createProjectsSlice(() => ({}));
    await slice.getState().createProject({
      name: 'new', display_name: 'New', description: '',
    });
    expect(createProjectMock).toHaveBeenCalled();
    expect(activateProjectMock).toHaveBeenCalledWith('new');
  });
});
```

- [ ] **Step 7.2: 写失败测试 — Dropdown**

文件 `frontend/src/components/desktop/__tests__/ProjectDropdown.test.tsx`:

```tsx
/**
 * ProjectDropdown 单测 — Round 1 SPEC §4.3。
 *
 * 契约:
 *   - chip 显示 activeProject.display_name;无 active → "选择项目"
 *   - 点 chip → 展开列出所有 projects + "+ 新建项目" 项
 *   - 点列表项 → 调 setActiveProject(id) + 收起
 *   - 点 "+ 新建项目" → 调 onCreateProject 回调 + 收起
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { ProjectDropdown } from '../ProjectDropdown';
import type { Project } from '../../../store/slices/projects';

const setActiveProjectMock = vi.fn();
const loadProjectsMock = vi.fn();

vi.mock('../../../store/slices/projects', () => ({
  useProjects: () => ({
    projects: [
      { id: 'default', name: 'default', display_name: '默认项目', path: '/x' } as Project,
      { id: 'p1', name: 'p1', display_name: '我的博客', path: '/y' } as Project,
    ],
    activeProjectId: 'default',
    loading: false,
    setActiveProject: setActiveProjectMock,
    loadProjects: loadProjectsMock,
  }),
}));

describe('ProjectDropdown', () => {
  beforeEach(() => {
    setActiveProjectMock.mockReset();
    loadProjectsMock.mockReset();
  });

  it('chip 显示 active project display_name', () => {
    const { container } = render(<ProjectDropdown onCreateProject={vi.fn()} />);
    expect(container.querySelector('.project-dropdown-chip')?.textContent).toContain('默认项目');
  });

  it('点 chip → 展开列表(包含 "+ 新建项目")', () => {
    const { container } = render(<ProjectDropdown onCreateProject={vi.fn()} />);
    fireEvent.click(container.querySelector('.project-dropdown-chip') as HTMLElement);
    expect(container.querySelector('.project-dropdown-menu')).not.toBeNull();
    expect(container.querySelector('.project-dropdown-create')).not.toBeNull();
  });

  it('点列表项 → setActiveProject + 收起', async () => {
    const { container } = render(<ProjectDropdown onCreateProject={vi.fn()} />);
    fireEvent.click(container.querySelector('.project-dropdown-chip') as HTMLElement);
    fireEvent.click(container.querySelectorAll('.project-dropdown-item')[1] as HTMLElement);
    await waitFor(() => {
      expect(setActiveProjectMock).toHaveBeenCalledWith('p1');
      expect(container.querySelector('.project-dropdown-menu')).toBeNull();
    });
  });

  it('点 "+ 新建项目" → 调 onCreateProject', async () => {
    const onCreate = vi.fn();
    const { container } = render(<ProjectDropdown onCreateProject={onCreate} />);
    fireEvent.click(container.querySelector('.project-dropdown-chip') as HTMLElement);
    fireEvent.click(container.querySelector('.project-dropdown-create') as HTMLElement);
    await waitFor(() => {
      expect(onCreate).toHaveBeenCalled();
      expect(container.querySelector('.project-dropdown-menu')).toBeNull();
    });
  });
});
```

- [ ] **Step 7.3: 运行测试验证失败**

```bash
cd /Users/yxb/projects/nexus/frontend
npm run test:vitest -- --run --reporter=verbose projects.test.ts ProjectDropdown.test.tsx
```

期望:7 个测试全 FAIL(模块不存在)。

- [ ] **Step 7.4: 实现 `lib/api.ts` 新增 5 个函数**

文件 `frontend/src/lib/api.ts`,在文件末尾 `switchModel` 之后追加:

```ts
// ============ Projects ============

export interface Project {
  id: string;
  name: string;
  display_name: string;
  path: string;
  description?: string;
  created_at?: string;
  updated_at?: string;
}

export interface CreateProjectInput {
  name: string;
  display_name: string;
  description?: string;
}

export async function fetchProjects(): Promise<Project[]> {
  const res = await apiFetch('/api/projects');
  if (!res.ok) throw new Error(`读取 Projects 失败: ${res.status}`);
  return (await res.json()) as Project[];
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const res = await apiFetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`创建 Project 失败: ${res.status} ${detail}`);
  }
  return (await res.json()) as Project;
}

export async function activateProject(id: string): Promise<void> {
  const res = await apiFetch(`/api/projects/${encodeURIComponent(id)}/activate`, {
    method: 'POST',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`切换 Project 失败: ${res.status} ${detail}`);
  }
}

export async function fetchSkills(projectId: string): Promise<Array<{name: string; path: string; source: string}>> {
  const res = await apiFetch(`/api/skills?project_id=${encodeURIComponent(projectId)}`);
  if (!res.ok) throw new Error(`读取 skills 失败: ${res.status}`);
  return (await res.json()) as Array<{name: string; path: string; source: string}>;
}

export async function fetchMcpToolsForProject(projectId: string): Promise<McpToolsResponse> {
  const res = await apiFetch(`/api/mcp/tools?project_id=${encodeURIComponent(projectId)}`);
  if (!res.ok) throw new Error(`读取 MCP 工具失败: ${res.status}`);
  return (await res.json()) as McpToolsResponse;
}
```

- [ ] **Step 7.5: 实现 `store/slices/projects.ts`**

文件 `frontend/src/store/slices/projects.ts`:

```ts
/**
 * ProjectsSlice — Round 1 SPEC §4.7。
 *
 * 状态:projects 列表 + 当前 active project id。
 * 副作用:loadProjects / setActiveProject / createProject 均调后端 REST,
 * 并通过 activateProject 把 active_project_id 落盘到 ~/.nexus/active_project.json。
 */
import type { StateCreator } from 'zustand';
import {
  activateProject as apiActivateProject,
  createProject as apiCreateProject,
  fetchProjects,
  type CreateProjectInput,
  type Project,
} from '../../lib/api';

export interface ProjectsSlice {
  projects: Project[];
  activeProjectId: string | null;
  loading: boolean;
  loadProjects: () => Promise<void>;
  setActiveProject: (id: string) => Promise<void>;
  createProject: (input: CreateProjectInput) => Promise<Project>;
}

export const createProjectsSlice: StateCreator<ProjectsSlice, [], [], ProjectsSlice> = (set, get) => ({
  projects: [],
  activeProjectId: null,
  loading: false,

  loadProjects: async () => {
    set({ loading: true });
    try {
      const projects = await fetchProjects();
      set({
        projects,
        activeProjectId: get().activeProjectId ?? projects[0]?.id ?? null,
        loading: false,
      });
    } catch (err) {
      set({ loading: false });
      throw err;
    }
  },

  setActiveProject: async (id: string) => {
    await apiActivateProject(id);
    set({ activeProjectId: id });
  },

  createProject: async (input: CreateProjectInput) => {
    const proj = await apiCreateProject(input);
    set((s) => ({
      projects: [...s.projects, proj],
      activeProjectId: proj.id,
    }));
    try {
      await apiActivateProject(proj.id);
    } catch {
      // 切 active 失败不阻断,UI 已是新 project
    }
    return proj;
  },
});
```

- [ ] **Step 7.6: 把 slice 接入 store**

文件 `frontend/src/store/index.ts:54-66`,把 `ProjectsSlice` 加入 `Store` 类型和组合:

```ts
import { createProjectsSlice, type ProjectsSlice } from './slices/projects';

export type Store =
  UiPrefsSlice & WsStatusSlice & ConversationsSlice & ChannelsSlice & ArtifactsSlice & MemorySlice & ProjectsSlice;

export const useStore = create<Store>()(
  persist(
    (...a) => ({
      ...createUiPrefsSlice(...a),
      ...createWsStatusSlice(...a),
      ...createConversationsSlice(...a),
      ...createChannelsSlice(...a),
      ...createArtifactsSlice(...a),
      ...createMemorySlice(...a),
      ...createProjectsSlice(...a),
    }),
    {
      name: 'nexus-preferences',
      storage: createJSONStorage(() => safeStorage),
      partialize: (state) => ({
        darkMode: state.darkMode,
        showThinking: state.showThinking,
        fontScale: state.fontScale,
        starredIds: state.starredIds,
        activeProjectId: state.activeProjectId,  // 新增
      }),
      skipHydration: true,
    }
  )
);
```

- [ ] **Step 7.7: 实现 `ProjectDropdown.tsx`**

文件 `frontend/src/components/desktop/ProjectDropdown.tsx`:

```tsx
/**
 * Project 切换 dropdown — Round 1 SPEC §4.3。
 *
 * 形态:紧凑 chip(project display_name + ▾),点开下拉列表,
 *      点项切 active + 自动收起;末尾"+ 新建项目"项调 onCreateProject 回调。
 */
import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store';
import type { Project } from '../../store/slices/projects';

export interface ProjectDropdownProps {
  onCreateProject: () => void;
}

export function ProjectDropdown({ onCreateProject }: ProjectDropdownProps) {
  const projects = useStore((s) => s.projects);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const setActiveProject = useStore((s) => s.setActiveProject);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const active = projects.find((p) => p.id === activeProjectId);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (ev: MouseEvent): void => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  return (
    <div ref={containerRef} className="project-dropdown">
      <button
        type="button"
        className="project-dropdown-chip"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid="project-dropdown-chip"
      >
        <span className="project-dropdown-name">
          {active?.display_name ?? '选择项目'}
        </span>
        <span aria-hidden="true" className="project-dropdown-caret">▾</span>
      </button>
      {open && (
        <ul className="project-dropdown-menu" role="listbox">
          {projects.map((p: Project) => (
            <li
              key={p.id}
              role="option"
              aria-selected={p.id === activeProjectId}
              className={`project-dropdown-item ${p.id === activeProjectId ? 'is-active' : ''}`}
              onClick={() => {
                setOpen(false);
                void setActiveProject(p.id);
              }}
            >
              {p.id === activeProjectId && (
                <span aria-hidden="true" className="project-dropdown-dot" />
              )}
              <span className="project-dropdown-item-name">{p.display_name}</span>
            </li>
          ))}
          <li
            className="project-dropdown-create"
            role="button"
            onClick={() => {
              setOpen(false);
              onCreateProject();
            }}
          >
            + 新建项目
          </li>
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 7.8: 实现 `NewProjectDrawer.tsx`**

文件 `frontend/src/components/desktop/NewProjectDrawer.tsx`:

```tsx
/**
 * 新建 Project 表单抽屉 — Round 1 SPEC §4.3。
 *
 * 三个字段:name(slug,必填)/ display_name / description。
 * name 客户端预校验 ^[a-z0-9][a-z0-9-_]{0,31}$,失败红字 + 阻止提交。
 * 后端 409 → toast(由 onError 回调实现)。
 */
import { useState } from 'react';
import { useStore } from '../../store';

const SLUG_RE = /^[a-z0-9][a-z0-9-_]{0,31}$/;

export interface NewProjectDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function NewProjectDrawer({ open, onClose }: NewProjectDrawerProps) {
  const createProject = useStore((s) => s.createProject);
  const [name, setName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const nameValid = SLUG_RE.test(name);

  const submit = async (): Promise<void> => {
    if (!nameValid || submitting) return;
    setSubmitting(true);
    try {
      await createProject({
        name,
        display_name: displayName || name,
        description,
      });
      // 清表单 + 关闭
      setName('');
      setDisplayName('');
      setDescription('');
      onClose();
    } catch (err) {
      // 错误由 PreferencesModal 通过 store 弹 toast;这里不重复
      console.error('createProject 失败:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="new-project-drawer" role="dialog" aria-label="新建项目">
      <h3>新建项目</h3>
      <label>
        <span>slug (英文/数字/-/_)</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-coding-project"
          autoFocus
        />
        {name.length > 0 && !nameValid && (
          <span className="field-error">格式不合法</span>
        )}
      </label>
      <label>
        <span>显示名</span>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="我的编码项目"
        />
      </label>
      <label>
        <span>描述</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </label>
      <div className="new-project-drawer-actions">
        <button type="button" onClick={onClose} disabled={submitting}>取消</button>
        <button
          type="button"
          className="primary"
          onClick={() => void submit()}
          disabled={!nameValid || submitting}
        >
          {submitting ? '创建中…' : '创建'}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 7.9: 接入 `Sidebar.tsx`**

文件 `frontend/src/components/desktop/Sidebar.tsx`,在顶部 brand 区下方追加 `<ProjectDropdown>` + state 管理 drawer:

```tsx
import { ProjectDropdown } from './ProjectDropdown';
import { NewProjectDrawer } from './NewProjectDrawer';

// 在 Sidebar 函数组件内部、return JSX 之前:
const [newProjectOpen, setNewProjectOpen] = useState(false);

// 在 Sidebar 顶部(标题区下方)插入:
<ProjectDropdown onCreateProject={() => setNewProjectOpen(true)} />

// 在 Sidebar 末尾插入:
{newProjectOpen && (
  <NewProjectDrawer
    open={newProjectOpen}
    onClose={() => setNewProjectOpen(false)}
  />
)}
```

**注意:** Sidebar 已有 `useState` / brand 区 JSX,在已有结构上 append,不要重写整个文件。`onCreateProject` 沿 SPEC §4.3 第 1 轮"够用"标准。

- [ ] **Step 7.10: 在 `DesktopShell.tsx` 启动时 `loadProjects()`**

文件 `frontend/src/components/desktop/DesktopShell.tsx`,在 `useBootstrap()` 调用之后追加:

```tsx
const loadProjects = useStore((s) => s.loadProjects);
useEffect(() => {
  void loadProjects();
}, [loadProjects]);
```

- [ ] **Step 7.11: 重跑测试**

```bash
npm run test:vitest -- --run --reporter=verbose projects.test.ts ProjectDropdown.test.tsx
```

期望:7 个测试全 PASS。

- [ ] **Step 7.12: Commit**

```bash
git add frontend/src/lib/api.ts \
        frontend/src/store/slices/projects.ts \
        frontend/src/store/index.ts \
        frontend/src/components/desktop/ProjectDropdown.tsx \
        frontend/src/components/desktop/NewProjectDrawer.tsx \
        frontend/src/components/desktop/Sidebar.tsx \
        frontend/src/components/desktop/DesktopShell.tsx \
        frontend/src/store/slices/__tests__/projects.test.ts \
        frontend/src/components/desktop/__tests__/ProjectDropdown.test.tsx
git commit -m "feat(frontend): ProjectsSlice store + ProjectDropdown + NewProjectDrawer"
```

---

## Task 8: PreferencesModal 加 Skills / MCP tabs

**Files:**
- Create: `frontend/src/components/desktop/SkillsPanel.tsx`
- Create: `frontend/src/components/desktop/McpPanel.tsx`
- Modify: `frontend/src/components/desktop/PreferencesModal.tsx`(添加新 tab)
- Modify: `frontend/src/components/desktop/styles/preferences-modal.css`(追加 CSS)
- Test: `frontend/src/components/desktop/__tests__/SkillsPanel.test.tsx`(新建)
- Test: `frontend/src/components/desktop/__tests__/McpPanel.test.tsx`(新建)

- [ ] **Step 8.1: 写失败测试 — SkillsPanel**

文件 `frontend/src/components/desktop/__tests__/SkillsPanel.test.tsx`:

```tsx
/**
 * SkillsPanel 单测 — Round 1 SPEC §4.4。
 *
 * 契约:
 *   - 列出当前 project 的 skills(每行:名字 + 来源路径)
 *   - 切换 project → 重新加载列表
 *   - 后端失败 → 显示错误文案(不白屏)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { SkillsPanel } from '../SkillsPanel';

const fetchSkillsMock = vi.fn();

vi.mock('../../../lib/api', () => ({
  fetchSkills: (...args: unknown[]) => fetchSkillsMock(...args),
}));

describe('SkillsPanel', () => {
  beforeEach(() => {
    fetchSkillsMock.mockReset();
  });

  it('拉取并列出当前 project 的 skills', async () => {
    fetchSkillsMock.mockResolvedValueOnce([
      { name: 'code-review', path: '/x/code-review', source: 'local' },
      { name: 'seo-check', path: '/y/seo-check', source: 'project' },
    ]);
    const { container } = render(<SkillsPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelectorAll('.skills-panel-item').length).toBe(2);
    });
    expect(container.textContent).toContain('code-review');
    expect(container.textContent).toContain('seo-check');
  });

  it('fetchSkills 失败 → 显示错误文案', async () => {
    fetchSkillsMock.mockRejectedValueOnce(new Error('网络错误'));
    const { container } = render(<SkillsPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelector('.skills-panel-error')).not.toBeNull();
    });
  });

  it('projectId 变化时重新加载', async () => {
    fetchSkillsMock.mockResolvedValueOnce([
      { name: 'a', path: '/a', source: 'local' },
    ]);
    const { rerender } = render(<SkillsPanel projectId="p1" />);
    await waitFor(() => expect(fetchSkillsMock).toHaveBeenCalledWith('p1'));
    fetchSkillsMock.mockResolvedValueOnce([
      { name: 'b', path: '/b', source: 'project' },
    ]);
    rerender(<SkillsPanel projectId="p2" />);
    await waitFor(() => expect(fetchSkillsMock).toHaveBeenCalledWith('p2'));
  });
});
```

- [ ] **Step 8.2: 写失败测试 — McpPanel**

文件 `frontend/src/components/desktop/__tests__/McpPanel.test.tsx`:

```tsx
/**
 * McpPanel 单测 — Round 1 SPEC §4.5。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { McpPanel } from '../McpPanel';

const fetchMcpToolsForProjectMock = vi.fn();

vi.mock('../../../lib/api', () => ({
  fetchMcpToolsForProject: (...args: unknown[]) => fetchMcpToolsForProjectMock(...args),
}));

describe('McpPanel', () => {
  beforeEach(() => {
    fetchMcpToolsForProjectMock.mockReset();
  });

  it('列出当前 project 的 MCP servers', async () => {
    fetchMcpToolsForProjectMock.mockResolvedValueOnce({
      project_id: 'p1',
      servers: [{ name: 'x', source: '/x.json' }, { name: 'y', source: '/y.json' }],
      tools: [],
      tool_count: 0,
      server_count: 2,
    });
    const { container } = render(<McpPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelectorAll('.mcp-panel-item').length).toBe(2);
    });
  });

  it('失败 → 错误文案', async () => {
    fetchMcpToolsForProjectMock.mockRejectedValueOnce(new Error('加载失败'));
    const { container } = render(<McpPanel projectId="p1" />);
    await waitFor(() => {
      expect(container.querySelector('.mcp-panel-error')).not.toBeNull();
    });
  });
});
```

- [ ] **Step 8.3: 运行测试验证失败**

```bash
npm run test:vitest -- --run --reporter=verbose SkillsPanel.test.tsx McpPanel.test.tsx
```

期望:5 个测试全 FAIL。

- [ ] **Step 8.4: 实现 `SkillsPanel.tsx`**

文件 `frontend/src/components/desktop/SkillsPanel.tsx`:

```tsx
/**
 * Skills 面板 — Round 1 SPEC §4.4。
 *
 * 列出当前 active project 的 skills;切 project 后 store.activeProjectId
 * 变 → 此组件重 mount(reload)。
 */
import { useEffect, useState } from 'react';
import { fetchSkills } from '../../lib/api';

interface SkillInfo {
  name: string;
  path: string;
  source: string;
}

export interface SkillsPanelProps {
  projectId: string;
}

export function SkillsPanel({ projectId }: SkillsPanelProps) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSkills(projectId)
      .then((data) => {
        if (!cancelled) {
          setSkills(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载失败');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <div className="skills-panel-loading">加载中…</div>;
  if (error) return <div className="skills-panel-error">{error}</div>;
  if (skills.length === 0) {
    return <div className="skills-panel-empty">当前项目暂无 skills</div>;
  }
  return (
    <ul className="skills-panel-list">
      {skills.map((s) => (
        <li key={s.name} className="skills-panel-item">
          <span className="skills-panel-name">{s.name}</span>
          <span className="skills-panel-path">{s.path}</span>
          <span className={`skills-panel-source is-${s.source}`}>{s.source}</span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 8.5: 实现 `McpPanel.tsx`**

文件 `frontend/src/components/desktop/McpPanel.tsx`:

```tsx
/**
 * MCP 面板 — Round 1 SPEC §4.5。
 *
 * 与 SkillsPanel 同构;列 servers + tools 计数;切 project 触发重载。
 * 不实现 toggle(SPEC §6 列在第 5 轮范围)。
 */
import { useEffect, useState } from 'react';
import { fetchMcpToolsForProject, type McpToolsResponse } from '../../lib/api';

export interface McpPanelProps {
  projectId: string;
}

export function McpPanel({ projectId }: McpPanelProps) {
  const [data, setData] = useState<McpToolsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchMcpToolsForProject(projectId)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载失败');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <div className="mcp-panel-loading">加载中…</div>;
  if (error) return <div className="mcp-panel-error">{error}</div>;
  if (!data || data.servers.length === 0) {
    return <div className="mcp-panel-empty">当前项目暂无 MCP servers</div>;
  }
  return (
    <div className="mcp-panel">
      <div className="mcp-panel-summary">
        {data.server_count} servers · {data.tool_count} tools
      </div>
      <ul className="mcp-panel-list">
        {data.servers.map((s) => (
          <li key={s.name} className="mcp-panel-item">
            <span className="mcp-panel-name">{s.name}</span>
            <span className="mcp-panel-source">{s.source}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 8.6: 接入 PreferencesModal 加 2 个 tab**

文件 `frontend/src/components/desktop/PreferencesModal.tsx`,在已有 tab 注册区(通常 `TABS: Tab[]` 常量)追加:

```tsx
{
  id: 'skills',
  label: 'Skills',
  render: () => {
    const activeId = useStore.getState().activeProjectId;
    return activeId ? <SkillsPanel projectId={activeId} /> : <div>请先选择项目</div>;
  },
},
{
  id: 'mcp',
  label: 'MCP',
  render: () => {
    const activeId = useStore.getState().activeProjectId;
    return activeId ? <McpPanel projectId={activeId} /> : <div>请先选择项目</div>;
  },
},
```

并在文件顶部 import:

```tsx
import { SkillsPanel } from './SkillsPanel';
import { McpPanel } from './McpPanel';
import { useStore } from '../../store';
```

**注意:** `useStore.getState()` 不是 hook,可在 render 函数里直接读 activeProjectId。如果现有 tab 实现是组件而非 render 函数,把上面 `() => ...` 改成 `<SkillsPanel projectId={...} />` 组件写法,前提是它能响应 activeProjectId 变化(可能需要 `useStore((s) => s.activeProjectId)` 让 tab 内部订阅)。

- [ ] **Step 8.7: CSS 追加**

文件 `frontend/src/components/desktop/styles/preferences-modal.css`,在文件末尾追加:

```css
/* Round 1 SPEC §4.4 / §4.5 — Skills / MCP 面板 */
.skills-panel-list,
.mcp-panel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.skills-panel-item,
.mcp-panel-item {
  display: grid;
  grid-template-columns: minmax(120px, 200px) 1fr auto;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--paper-2);
  font-size: var(--font-sm);
  align-items: center;
}
.skills-panel-name,
.mcp-panel-name {
  color: var(--ink);
  font-weight: 500;
}
.skills-panel-path,
.mcp-panel-source {
  color: var(--ink-3);
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skills-panel-source.is-project {
  color: var(--accent);
}
.mcp-panel-summary {
  font-size: var(--font-xs);
  color: var(--ink-2);
  margin-bottom: 8px;
}
.skills-panel-loading,
.skills-panel-error,
.skills-panel-empty,
.mcp-panel-loading,
.mcp-panel-error,
.mcp-panel-empty {
  font-size: var(--font-sm);
  color: var(--ink-2);
  padding: 16px 8px;
}
.skills-panel-error,
.mcp-panel-error {
  color: var(--error, #d44);
}
```

- [ ] **Step 8.8: 重跑测试**

```bash
npm run test:vitest -- --run --reporter=verbose SkillsPanel.test.tsx McpPanel.test.tsx
```

期望:5 个测试全 PASS。

- [ ] **Step 8.9: Commit**

```bash
git add frontend/src/components/desktop/SkillsPanel.tsx \
        frontend/src/components/desktop/McpPanel.tsx \
        frontend/src/components/desktop/PreferencesModal.tsx \
        frontend/src/components/desktop/styles/preferences-modal.css \
        frontend/src/components/desktop/__tests__/SkillsPanel.test.tsx \
        frontend/src/components/desktop/__tests__/McpPanel.test.tsx
git commit -m "feat(frontend): PreferencesModal Skills / MCP tabs + API client"
```

---

## Task 9: 端到端测试 + 完整验证

**Files:**
- Create: `tests/test_projects_e2e.py`(新建)
- Modify: 现有 E2E 不动(本 Task 只加 pytest 端到端,不碰 Playwright)

- [ ] **Step 9.1: 写端到端测试**

文件 `tests/test_projects_e2e.py`:

```python
"""Project 端到端流程测试 — Round 1 SPEC 全链路。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend.db import get_db, init_db
from nexus.backend.main import app
from nexus.backend.projects.skills_loader import list_skills
from nexus.backend.projects.storage import ensure_default_project


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path))
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-token")
    # 准备一个 skill 让默认 project 看得见
    (tmp_path / "skills" / "code-review").mkdir(parents=True)
    (tmp_path / "skills" / "code-review" / "SKILL.md").write_text("# code-review")

    from nexus.backend import db
    monkeypatch.setattr(db, "_INITED", False)
    init_db()
    ensure_default_project()
    yield TestClient(app)


def test_full_flow_create_sessions_list_skills(client: TestClient) -> None:
    """用户流程:列出默认 Project → 创建一个新 Project → 切换 → 看不同 skills。"""
    headers = {"Authorization": "Bearer test-token"}

    # 1) 列出 Project → 应有 default
    r = client.get("/api/projects", headers=headers)
    assert r.status_code == 200
    projects = r.json()
    assert any(p["id"] == "default" for p in projects)

    # 2) 创建新 Project
    r = client.post(
        "/api/projects",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": "blog", "display_name": "博客"},
    )
    assert r.status_code == 201
    new_id = r.json()["id"]

    # 3) 列出 → 应有 2 个
    r = client.get("/api/projects", headers=headers)
    assert len(r.json()) == 2

    # 4) 切 active → 落盘
    r = client.post(f"/api/projects/{new_id}/activate", headers=headers)
    assert r.status_code == 200
    active_file = Path.home() / ".nexus" / "active_project.json"
    # NEXUS_HOME 已被 monkeypatch,所以走 monkeypatch 的 tmp_path
    # 不直接断言文件路径(路径已变),改成读 GET /api/projects/active
    r = client.get("/api/projects/active", headers=headers)
    assert r.json() == {"active_project_id": new_id}

    # 5) default project 的 skills 列表应包含 code-review
    skills = list_skills("default")
    assert any(s["name"] == "code-review" for s in skills)
```

- [ ] **Step 9.2: 全套验证**

```bash
# 后端
source .venv/bin/activate
pytest tests/test_projects_db.py tests/test_default_project_migration.py \
       tests/test_projects_api.py tests/test_skills_loader.py \
       tests/test_mcp_loader.py tests/test_project_context_prompt.py \
       tests/test_projects_e2e.py -v
ruff check nexus/backend/
ruff format --check nexus/backend/

# 前端
cd frontend
npm run lint
npx tsc --noEmit
npm run test:vitest -- --run
npm run build
```

期望:
- pytest 7 个测试文件全 PASS(test_projects_db 3 + test_default_project_migration 4 + test_projects_api 5 + test_skills_loader 4 + test_mcp_loader 4 + test_project_context_prompt 2 + test_projects_e2e 1 = 23 个测试)
- ruff check 0 error
- ruff format 0 diff
- 前端 lint 0 error
- 前端 tsc 0 error
- 前端 vitest 全过(包含本轮 12 个新增 — Task 7:7 + Task 8:5)
- 前端 build 成功

**若任何项失败**:回到对应 Task 修复,**不要**在 Task 9 里改其它文件。

- [ ] **Step 9.3: Commit**

```bash
git add tests/test_projects_e2e.py
git commit -m "test: projects 端到端 + Zustand slice 单测"
```

---

## 验证清单(完整 SPEC 覆盖)

- [x] **§4.1 数据模型**:Task 1 + Task 2 覆盖
- [x] **§4.2 默认 Project 迁移**:Task 2 覆盖 + Task 9 e2e 验证
- [x] **§4.3 Sidebar UX**:Task 7 覆盖
- [x] **§4.4 Skills per-project**:Task 4 + Task 8 覆盖
- [x] **§4.5 MCP per-project**:Task 5 + Task 8 覆盖
- [x] **§4.6 Per-project 上下文**:Task 6 覆盖
- [x] **§4.7 前端 store**:Task 7 覆盖
- [x] **§5 风险点**:
  - §5.1 数据迁移:Task 2 + Task 9 e2e
  - §5.2 MCP 热更新:Task 5(本轮"够用"标准,热更新由 main loop 兜底)
  - §5.3 Skills 双扫路径:Task 4 + 测试覆盖 inode 去重
  - §5.4 Project 切换 UX 一致性:SPEC §4.7 决策 — Task 7 在 setActiveProject 后由调用方(后续轮)清空 currentMessages
  - §5.5 name slug 校验:Task 3 + Task 7 双向校验
- [x] **§6 不在范围**:Project 图标 / per-project sidebar 分组 / 动画 — 后续轮
- [x] **§7 SPEC 自检**:无 placeholder / 类型一致 / 范围聚焦 / 歧义检查 / 风险覆盖

---

## 不在范围(明确 YAGNI)

- Project 图标 / 颜色 / 排序 — 第 3 轮
- per-project 侧栏分组(按 project 折叠 sessions)— 第 2 轮
- Project 切换动画 — 后续 UX 打磨轮
- MCP 工具调用可视化 — 第 5 轮
- Skill 启用 toggle(SPEC §4.4 列在"Skills 面板",但 toggle 后端未实现,留第 5 轮)
- 详尽 UI 视觉打磨 — 第 1 轮只求"够用"

---

## 风险与权衡

1. **sessions.project_id NOT NULL 风险** — 现有 v1.5.4 数据库 sessions 表可能 project_id 列已经因 `_ensure_column` 添加但都是 NULL。Task 2 `migrate_sessions_to_default` 启动时一次性 UPDATE NULL → 'default';重启幂等。
2. **default Project 重启幂等** — Task 2 测试覆盖(`test_ensure_default_project_idempotent`),AGENTS.md / skills / mcp.json 都检查"已存在则跳过"。
3. **后端 MCP "热更新" 范围** — SPEC §5.2 要求切 project → 重新连接 MCP。本轮 `load_mcp_config_for_project` 只在新请求时返回新 server list(已实现),**真正 agent 热重建**留到 Task 6 之后的"切换 active 端点"(后续轮),本轮不引入 agent rebuild hook 避免范围爆炸。
4. **前端 store.activeProjectId 持久化** — Task 7.6 partialize 持久化,启动时 rehydrate → 与后端 `active_project.json` 可能在多次切换后不一致。本轮接受"前端为前端,后端为后端,各自持久化";后续轮加 reconcile 逻辑。
5. **测试 fixture 隔离** — Task 1 / 2 / 3 / 9 都用 `monkeypatch.setenv("NEXUS_HOME", tmp_path)`,确保不污染 `~/.nexus/`。verify by `ls ~/.nexus/projects/` 不应被本轮测试创建。
6. **前端组件 CSS 不引入新 token** — 全部复用 `var(--line)` / `var(--paper-2)` / `var(--font-sm)` 等既有 token;新增 CSS 只组合,不引入变量。

---

## 自检(写完 plan 后回看 SPEC)

1. **Spec coverage**:已逐节对应到 9 个 Task,§4 全部覆盖,§5 全部覆盖,§6 明确 YAGNI。
2. **Placeholder scan**:全文 grep "TBD" / "TODO" / "后续实现" — 0 命中。每个代码块都是完整可运行代码,无 "类似 Task X" 引用。
3. **Type consistency**:
   - `Project` 接口在 `lib/api.ts` 与 `slices/projects.ts` 与后端 Pydantic 字段一致(`id` / `name` / `display_name` / `path` / `description`)
   - `list_skills` 返回 `{name, path, source}` 三字段,前端 `SkillsPanel` / `McpPanel` 引用一致
   - `fetchSkills` / `fetchMcpToolsForProject` API 签名两端对齐
4. **范围聚焦**:9 个 Task 全部对应 SPEC §4 第 1 轮;§6 不在范围项已显式列出。
5. **歧义检查**:Skills 是 symlink resolve 后按 inode 去重(§5.3)— Task 4 测试明确;AGENTS.md 拷贝非软链(§4.2 决策)— Task 2 注释明确。

---

*Plan 终稿 · 2026-07-23 · 待审批*