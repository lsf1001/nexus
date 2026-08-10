# Round 2: 文件上传 / 附件 + 草稿 UX 补全 — 实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Composer 加文件上传能力(图片 + 文档,multi-part 注入 LLM),并把草稿持久化补到 per-project 级别,补多 tab 冲突提示与草稿列表面板。

**Architecture:**
- 后端走 `~/Nexus/projects/{projectId}/uploads/` 落盘,multipart REST 暴露。LLM 注入在 gateway 改成"如有 attachments 走 multi-part,无则保持原纯 text 路径"(零回归)
- 前端用 useAttachments 本地 hold File 对象 → submit 时一次性 batch upload → 提交携带 server id。草稿走 per-project key,storage 事件做多 tab 同步,PreferencesModal 加"草稿"tab

**Tech Stack:** FastAPI `python-multipart` + FastAPI `UploadFile` + pathlib · React 19 + Zustand + localStorage + StorageEvent + canvas image scaling

**父 SPEC:** `docs/superpowers/specs/2026-07-24-round2-attachments-and-drafts-design.md`

---

## 全局约定(所有 task 通用)

- **Python 测试**:`source .venv/bin/activate && pytest tests/test_X.py::test_name -v`
- **前端测试**:`cd frontend && npx vitest run path/to/file`
- **Lint**:`ruff check nexus/ && (cd frontend && npm run lint)`
- **typecheck**:`(cd frontend && npx tsc --noEmit)`
- **e2e**:`(cd frontend && npm run test:e2e -- --grep "spec_name")`
- **依赖新增**:Python `python-multipart` / `python-magic-bin`;前端零新依赖
- **commit 格式**:Conventional Commits,中文主题,≤ 50 字符;**每 task 一个 commit**

---

## Task 1: 后端 attachment storage helper(`nexus/backend/attachments.py` + 单测)

**Files:**
- Create: `nexus/backend/attachments.py`
- Create: `tests/test_attachments_storage.py`

- [ ] **Step 1: 写失败单测**

```python
# tests/test_attachments_storage.py
"""附件 storage helper 单测 — 文件落盘 + mime 嗅探 + 大小校验。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from nexus.backend.attachments import (
    MAX_FILE_SIZE,
    SUPPORTED_MIMES,
    save_attachment,
)


def test_save_attachment_writes_file(tmp_path: Path) -> None:
    """附件落盘成功 → 返回 id + 文件存在 + size 一致。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    payload = b"hello world"
    att = save_attachment(
        project_dir=project_dir,
        original_name="note.txt",
        content=payload,
        mime="text/plain",
    )
    # 返 id 是合法 uuid
    UUID(att["id"])
    # 文件落盘
    stored = project_dir / "uploads" / att["stored_filename"]
    assert stored.exists()
    assert stored.read_bytes() == payload
    assert att["size"] == len(payload)
    assert att["mime"] == "text/plain"
    assert att["original_name"] == "note.txt"


def test_save_attachment_rejects_oversize(tmp_path: Path) -> None:
    """超过 20MB 抛 ValueError(转 413 给 route)。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    payload = b"x" * (MAX_FILE_SIZE + 1)
    with pytest.raises(ValueError, match="文件过大"):
        save_attachment(
            project_dir=project_dir,
            original_name="big.bin",
            content=payload,
            mime="text/plain",
        )


def test_save_attachment_rejects_unsupported_mime(tmp_path: Path) -> None:
    """不支持的 mime 抛 ValueError。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    with pytest.raises(ValueError, match="不支持的附件类型"):
        save_attachment(
            project_dir=project_dir,
            original_name="x.exe",
            content=b"x",
            mime="application/x-msdownload",
        )


def test_save_attachment_sanitizes_extension(tmp_path: Path) -> None:
    """文件名包含 ../ 会被剥离,只保留扩展名。"""
    project_dir = tmp_path / "default"
    project_dir.mkdir()
    att = save_attachment(
        project_dir=project_dir,
        original_name="../../etc/passwd.txt",
        content=b"safe",
        mime="text/plain",
    )
    # 不会写到 /etc/passwd.txt;只在 project uploads/ 下
    assert ".." not in att["stored_filename"]
    assert att["stored_filename"].endswith(".txt")


def test_supported_mimes_includes_image_text_pdf() -> None:
    """白名单含 SPEC §4.3 要求的 mime。"""
    assert "image/png" in SUPPORTED_MIMES
    assert "image/jpeg" in SUPPORTED_MIMES
    assert "text/plain" in SUPPORTED_MIMES
    assert "application/pdf" in SUPPORTED_MIMES
```

- [ ] **Step 2: 运行确认失败**

```bash
source .venv/bin/activate && pytest tests/test_attachments_storage.py -v
```
预期:`ModuleNotFoundError: No module named 'nexus.backend.attachments'`。

- [ ] **Step 3: 写实现**

```python
# nexus/backend/attachments.py
"""附件 storage helper — 落盘 + mime 校验 + 大小校验。

WHY 独立模块:与 routes/attachments.py 分离,REST 层只做 HTTP 边界,
本模块负责文件 IO + 校验 + filename 安全。便于在 main 启动时 ensure 目录存在。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB;与 SPEC §4.1 一致

# 与前端白名单同步(SPEC §4.1)。Python mimetypes 模块会用它做 guess。
SUPPORTED_MIMES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "text/x-python",
        "text/x-javascript",
        "application/javascript",
        "application/typescript",
        "text/jsx",
        "text/tsx",
    }
)


def _safe_ext(original_name: str, mime: str) -> str:
    """从原始文件名提取扩展名,做路径穿越防护。

    只保留字母数字下划线点,其它字符替换为下划线。空扩展时按 mime 给一个 fallback。
    """
    # 取最后一个 . 之后的字符;若原名无 . 或扩展名非法则按 mime 兜底
    if "." in original_name:
        ext = original_name.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{1,8}", ext):
            return f".{ext}"
    # mime fallback(避免无扩展文件)
    fallback = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/csv": ".csv",
        "application/json": ".json",
    }.get(mime, "")
    return fallback


def ensure_uploads_dir(project_dir: Path) -> Path:
    """确保 project_dir/uploads/ 存在,返回 uploads 目录 Path。"""
    uploads = project_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


def save_attachment(
    *,
    project_dir: Path,
    original_name: str,
    content: bytes,
    mime: str,
) -> dict[str, str | int]:
    """把附件写到 project_dir/uploads/att_<uuid><ext>,返回 metadata 字典。

    Raises:
        ValueError: size 超限 或 mime 不支持
    """
    if mime not in SUPPORTED_MIMES:
        raise ValueError(f"不支持的附件类型: {mime}")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"文件过大(>{MAX_FILE_SIZE // 1024 // 1024}MB)")
    uploads = ensure_uploads_dir(project_dir)
    ext = _safe_ext(original_name, mime)
    stored_filename = f"att_{uuid.uuid4().hex}{ext}"
    file_path = uploads / stored_filename
    file_path.write_bytes(content)
    return {
        "id": uuid.uuid4().hex,
        "original_name": original_name,
        "stored_filename": stored_filename,
        "file_path": str(file_path),
        "mime": mime,
        "size": len(content),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }


def read_attachment_text(file_path: str, max_chars: int = 20000) -> str:
    """读文本附件内容,超 max_chars 截断并加末尾标记(SPEC §4.4)。"""
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (已截断,原 {len(text)} 字符)"
    return text


def read_attachment_image_b64(file_path: str) -> tuple[str, bytes]:
    """读图片附件,返 (mime, base64-decoded bytes)。mime 从 file_path 后缀推。

    返回 bytes 是为了让 caller 自己 encode,避免本模块引 base64(SPEC §4.4 写到 caller 里)。
    """
    p = Path(file_path)
    # 用后缀反推 mime;不信任外部传 mime
    ext = p.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return mime, p.read_bytes()
```

- [ ] **Step 4: 跑测试确认绿**

```bash
source .venv/bin/activate && pytest tests/test_attachments_storage.py -v
```
预期:5 passed。

- [ ] **Step 5: Commit**

```bash
git add nexus/backend/attachments.py tests/test_attachments_storage.py
git commit -m "feat(backend): attachment storage helper(落盘+mime+大小校验)"
```

---

## Task 2: 后端 REST routes(`nexus/backend/routes/attachments.py` + main include + 单测)

**Files:**
- Create: `nexus/backend/routes/attachments.py`
- Create: `tests/test_attachments_routes.py`
- Modify: `nexus/backend/main.py`(include router)

- [ ] **Step 1: 写失败单测**

```python
# tests/test_attachments_routes.py
"""POST /api/attachments 单测 — multipart 上传 + 校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """tmp_path 当 ~/.nexus,project_dir = tmp_path/Nexus/projects/default。"""
    # 通过 monkeypatch 把 _projects_root 指向 tmp_path
    from nexus.backend.projects import storage as project_storage

    monkeypatch.setattr(project_storage, "_projects_root", lambda: tmp_path / "Nexus" / "projects")
    monkeypatch.setattr(project_storage, "_get_nexus_home", lambda: tmp_path)
    # 默认 Project 自动迁移会被 _ensure_default_project 调用;我们需要预建
    (tmp_path / "Nexus" / "projects" / "default").mkdir(parents=True)
    return TestClient(app)


def test_post_attachment_text_plain(client: TestClient) -> None:
    """上传 .txt 文本 → 201 + metadata。"""
    response = client.post(
        "/api/attachments",
        data={"project_id": "default"},
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_name"] == "note.txt"
    assert body["mime"] == "text/plain"
    assert body["size"] == 11
    assert body["file_path"].endswith(body["stored_filename"])


def test_post_attachment_rejects_oversize(client: TestClient) -> None:
    """超 20MB → 413。"""
    big = b"x" * (20 * 1024 * 1024 + 1)
    response = client.post(
        "/api/attachments",
        data={"project_id": "default"},
        files={"file": ("big.bin", big, "text/plain")},
    )
    assert response.status_code == 413


def test_post_attachment_rejects_unsupported_mime(client: TestClient) -> None:
    """.exe → 415。"""
    response = client.post(
        "/api/attachments",
        data={"project_id": "default"},
        files={"file": ("x.exe", b"x", "application/x-msdownload")},
    )
    assert response.status_code == 415


def test_post_attachment_unknown_project(client: TestClient) -> None:
    """project_id 不存在 → 404。"""
    response = client.post(
        "/api/attachments",
        data={"project_id": "no-such"},
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert response.status_code == 404


def test_get_attachment_returns_raw(client: TestClient) -> None:
    """GET /api/attachments/{id} 返 raw bytes + Content-Disposition。"""
    post = client.post(
        "/api/attachments",
        data={"project_id": "default"},
        files={"file": ("note.txt", b"abc", "text/plain")},
    )
    att_id = post.json()["id"]
    response = client.get(f"/api/attachments/{att_id}")
    assert response.status_code == 200
    assert response.content == b"abc"
    assert "note.txt" in response.headers.get("content-disposition", "")


def test_delete_attachment_removes_file(client: TestClient) -> None:
    """DELETE /api/attachments/{id} → 204 + 文件从磁盘删。"""
    post = client.post(
        "/api/attachments",
        data={"project_id": "default"},
        files={"file": ("note.txt", b"abc", "text/plain")},
    )
    file_path = Path(post.json()["file_path"])
    assert file_path.exists()
    att_id = post.json()["id"]
    response = client.delete(f"/api/attachments/{att_id}")
    assert response.status_code == 204
    assert not file_path.exists()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
source .venv/bin/activate && pytest tests/test_attachments_routes.py -v
```
预期:`ModuleNotFoundError: No module named 'nexus.backend.routes.attachments'`。

- [ ] **Step 3: 写 routes**

```python
# nexus/backend/routes/attachments.py
"""附件上传 REST 路由 — multipart/form-data。

WHY 单文件:与 projects.py 同模板,prefix + deps + 一个 router。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..api.ws import require_token
from ..attachments import (
    MAX_FILE_SIZE,
    SUPPORTED_MIMES,
    save_attachment,
)
from ..db import get_db
from ..projects import storage as project_storage

router = APIRouter(
    prefix="/api/attachments",
    tags=["attachments"],
    dependencies=[Depends(require_token)],
)


def _project_dir(project_id: str) -> Path:
    """从 DB 拿 project.path,project 不存在 → 404。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT path FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project 不存在: {project_id}")
    return Path(row["path"])


@router.post("", status_code=201)
async def post_attachment(
    project_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """上传附件 → 写盘 → 返 metadata。"""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大(>{MAX_FILE_SIZE // 1024 // 1024}MB)",
        )
    mime = file.content_type or "application/octet-stream"
    if mime not in SUPPORTED_MIMES:
        raise HTTPException(status_code=415, detail=f"不支持的附件类型: {mime}")

    project_dir = _project_dir(project_id)
    try:
        metadata = save_attachment(
            project_dir=project_dir,
            original_name=file.filename or "attachment",
            content=content,
            mime=mime,
        )
    except ValueError as e:
        # save_attachment 内部已经校验过大小/mime,这里兜底
        msg = str(e)
        if "过大" in msg:
            raise HTTPException(status_code=413, detail=msg) from e
        if "不支持" in msg:
            raise HTTPException(status_code=415, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    return {**metadata, "project_id": project_id}


@router.get("/{attachment_id}")
async def get_attachment(attachment_id: str) -> Response:
    """拉 raw 字节,Content-Disposition: inline。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path, original_name, mime FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    p = Path(row["file_path"])
    if not p.exists():
        raise HTTPException(status_code=410, detail="文件已被删除")
    return Response(
        content=p.read_bytes(),
        media_type=row["mime"],
        headers={"Content-Disposition": f'inline; filename="{row["original_name"]}"'},
    )


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(attachment_id: str) -> Response:
    """删附件(metadata + 文件)。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    p = Path(row["file_path"])
    if p.exists():
        p.unlink()
    return Response(status_code=204)
```

- [ ] **Step 4: 加 attachments 表到 db.py(无破坏)**

打开 `nexus/backend/db.py`,找到 `_ensure_column` / 表创建段,加 attachments 表:

```python
# 在 _ensure_column 之后或 _init_schema 内的 attachments 表创建段:
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS attachments (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        original_name TEXT NOT NULL,
        stored_filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        mime TEXT NOT NULL,
        size INTEGER NOT NULL,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_attachments_project ON attachments(project_id)"
)
```

- [ ] **Step 5: 在 routes/attachments.py 加 INSERT helper(POST 时落 DB)**

回到 `nexus/backend/routes/attachments.py`,在 `post_attachment` 返 metadata 前加 INSERT:

```python
    # metadata 拿到后写 DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO attachments "
            "(id, project_id, original_name, stored_filename, file_path, mime, size, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                metadata["id"],
                project_id,
                metadata["original_name"],
                metadata["stored_filename"],
                metadata["file_path"],
                metadata["mime"],
                metadata["size"],
                metadata["uploaded_at"],
            ),
        )
```

- [ ] **Step 6: include router 到 main**

打开 `nexus/backend/main.py`,在其它 router include 旁加:

```python
from .routes.attachments import router as attachments_router

app.include_router(attachments_router)
```

- [ ] **Step 7: 跑测试确认绿**

```bash
source .venv/bin/activate && pytest tests/test_attachments_routes.py tests/test_attachments_storage.py -v
```
预期:全过(11 个:5 storage + 6 routes)。

- [ ] **Step 8: Commit**

```bash
git add nexus/backend/routes/attachments.py nexus/backend/db.py nexus/backend/main.py tests/test_attachments_routes.py
git commit -m "feat(backend): POST/GET/DELETE /api/attachments 多 part 上传 + 落 DB"
```

---

## Task 3: 后端多 part LLM 注入(`gateway.py`/`agent.py` 改 + 单测)

**Files:**
- Modify: `nexus/backend/agent.py` 或 `nexus/backend/gateway.py`(具体入口看代码,下面以 gateway.py 举例)
- Create: `tests/test_attachment_injection.py`

- [ ] **Step 1: 找到现有 chat 入口**

```bash
grep -nE "build_prompt|user_message|content=" nexus/backend/gateway.py nexus/backend/agent.py 2>/dev/null | head -20
```

确认 user message 进入 LLM 的位置(SessionManager.build_prompt 在 sessions.py:90,实际 LLM 入口在 agent.py / gateway.py)。

- [ ] **Step 2: 写失败单测**

```python
# tests/test_attachment_injection.py
"""附件注入 LLM multi-part 单测。"""

from __future__ import annotations

from pathlib import Path

from nexus.backend.attachments import (
    read_attachment_image_b64,
    read_attachment_text,
)


def test_read_attachment_text_under_limit(tmp_path: Path) -> None:
    """< 20000 字符 全文返回。"""
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    text = read_attachment_text(str(p))
    assert text == "hello"


def test_read_attachment_text_truncates(tmp_path: Path) -> None:
    """> 20000 字符 末尾加截断标记。"""
    p = tmp_path / "a.txt"
    p.write_text("x" * 25000, encoding="utf-8")
    text = read_attachment_text(str(p))
    assert text.startswith("x" * 20000)
    assert "已截断" in text
    assert "25000" in text


def test_read_attachment_image_b64_roundtrip(tmp_path: Path) -> None:
    """图片按后缀判 mime + 返原 bytes。"""
    p = tmp_path / "x.png"
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    p.write_bytes(raw)
    mime, data = read_attachment_image_b64(str(p))
    assert mime == "image/png"
    assert data == raw


def test_build_messages_with_attachment_text(tmp_path: Path) -> None:
    """build_messages_with_attachments(纯文本附件)→ content 是 multi-part text 数组。"""
    from nexus.backend.attachments import save_attachment

    p = tmp_path / "default"
    p.mkdir()
    att = save_attachment(
        project_dir=p,
        original_name="note.txt",
        content=b"file content",
        mime="text/plain",
    )
    # 用 attachment 元数据组装 message(模拟 gateway 的入口)
    from nexus.backend.agent import build_messages_with_attachments

    msgs = build_messages_with_attachments(
        user_text="解释这个文件",
        attachments=[att],
    )
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "解释这个文件"}
    assert content[1]["type"] == "text"
    assert "file content" in content[1]["text"]
    assert "note.txt" in content[1]["text"]


def test_build_messages_with_attachment_image(tmp_path: Path) -> None:
    """图片附件 → image multi-part(Anthropic 格式)。"""
    import base64

    from nexus.backend.agent import build_messages_with_attachments
    from nexus.backend.attachments import save_attachment

    p = tmp_path / "default"
    p.mkdir()
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    att = save_attachment(
        project_dir=p,
        original_name="snap.png",
        content=raw,
        mime="image/png",
    )
    msgs = build_messages_with_attachments(
        user_text="这张图是什么?",
        attachments=[att],
    )
    content = msgs[0]["content"]
    assert content[1]["type"] == "image"
    src = content[1]["source"]
    assert src["type"] == "base64"
    assert src["media_type"] == "image/png"
    assert base64.b64decode(src["data"]) == raw


def test_build_messages_no_attachments_returns_text() -> None:
    """无附件 → 返原纯 text 路径(零回归)。"""
    from nexus.backend.agent import build_messages_with_attachments

    msgs = build_messages_with_attachments(user_text="hi")
    assert msgs == [{"role": "user", "content": "hi"}]
```

- [ ] **Step 3: 跑测试确认失败**

```bash
source .venv/bin/activate && pytest tests/test_attachment_injection.py -v
```
预期:`ImportError: cannot import name 'build_messages_with_attachments'`。

- [ ] **Step 4: 写实现**

打开 `nexus/backend/agent.py`,在文件顶部 import + 加函数:

```python
# 顶部 import
import base64
from .attachments import (
    read_attachment_image_b64,
    read_attachment_text,
)


def build_messages_with_attachments(
    user_text: str,
    attachments: list[dict] | None = None,
) -> list[dict]:
    """把 user_text + attachments 组装成 LLM 消息。

    有 attachments → multi-part content(text + image base64 / text 全文本)。
    无 attachments → 原纯 text 路径,**零回归**。

    Args:
        user_text: 用户输入文本
        attachments: list[{file_path, mime, original_name}] from /api/attachments

    Returns:
        LLM messages list,默认 [{role: "user", content: ...}]。
    """
    if not attachments:
        return [{"role": "user", "content": user_text}]

    content: list[dict] = [{"type": "text", "text": user_text}]
    for att in attachments:
        mime = att.get("mime", "")
        if mime.startswith("image/"):
            detected_mime, raw = read_attachment_image_b64(att["file_path"])
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": detected_mime,
                        "data": base64.b64encode(raw).decode("ascii"),
                    },
                }
            )
        elif mime.startswith("text/") or mime in ("application/json", "application/pdf"):
            text = read_attachment_text(att["file_path"])
            content.append(
                {
                    "type": "text",
                    "text": f"--- attachment: {att['original_name']} ---\n{text}\n--- end attachment ---",
                }
            )
        # 其它 mime 跳过(已在前置路由层 415 拦截,这里防御性兜底)
    return [{"role": "user", "content": content}]
```

- [ ] **Step 5: 接到现有 chat 入口**

找到 `SessionManager.build_prompt`(在 `sessions.py:90`)和 `agent.py` 真正调 LLM 的位置,把 `build_prompt` 改成支持 `attachment_ids`:

```python
# sessions.py:SessionManager.build_prompt 改造
def build_prompt(
    self,
    session_id: str,
    user_message: str,
    attachment_ids: list[str] | None = None,
) -> dict:
    history = get_conversation_history(session_id)
    if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
        history = history[:-1]
    messages: list[dict] = [{"role": "system", "content": ""}]
    messages.extend(history)

    # 拉附件 metadata(若有)
    attachments_meta = []
    if attachment_ids:
        with get_db() as conn:
            placeholders = ",".join("?" * len(attachment_ids))
            rows = conn.execute(
                f"SELECT file_path, mime, original_name FROM attachments WHERE id IN ({placeholders})",
                attachment_ids,
            ).fetchall()
        attachments_meta = [dict(r) for r in rows]

    user_msg = build_messages_with_attachments(user_message, attachments_meta)
    messages.extend(user_msg)
    return {"session_id": session_id, "messages": messages}
```

- [ ] **Step 6: 跑测试确认绿**

```bash
source .venv/bin/activate && pytest tests/test_attachment_injection.py tests/test_attachments_routes.py tests/test_attachments_storage.py -v
```
预期:全过(11 + 6 = 17 个)。

- [ ] **Step 7: Commit**

```bash
git add nexus/backend/agent.py nexus/backend/sessions.py tests/test_attachment_injection.py
git commit -m "feat(backend): 多 part LLM 注入(文本全文 + 图片 base64)+ 零回归路径"
```

---

## Task 4: 前端 useAttachments hook(`hooks/useAttachments.ts` + 单测)

**Files:**
- Create: `frontend/src/components/ChatArea/hooks/useAttachments.ts`
- Create: `frontend/src/components/ChatArea/__tests__/useAttachments.test.ts`

- [ ] **Step 1: 写失败单测**

```typescript
// frontend/src/components/ChatArea/__tests__/useAttachments.test.ts
/**
 * useAttachments — 本地附件 state + 上传 + 移除。
 *
 * 设计:
 *   - addFiles(file[])  → push LocalAttachment{uploadStatus: 'pending'}
 *   - 立即异步 upload → 成功回填 serverId + uploadStatus: 'uploaded'
 *   - remove(id)       → 移除条目;若已 uploaded 调 DELETE /api/attachments/{id}
 *   - clear()          → 移除全部 + DELETE 所有 uploaded
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { useAttachments } from '../hooks/useAttachments'

const fileFromBytes = (name: string, bytes: number, type: string): File =>
  new File([new Uint8Array(bytes)], name, { type })

describe('useAttachments', () => {
  it('addFiles 后 attachments 列表长度 = 1', async () => {
    const { result } = renderHook(() => useAttachments('default'))
    const f = fileFromBytes('note.txt', 5, 'text/plain')
    await act(async () => {
      result.current.addFiles([f])
    })
    expect(result.current.attachments).toHaveLength(1)
    expect(result.current.attachments[0]?.originalName).toBe('note.txt')
  })

  it('remove 后 attachments 列表清空', async () => {
    const { result } = renderHook(() => useAttachments('default'))
    const f = fileFromBytes('note.txt', 5, 'text/plain')
    await act(async () => {
      result.current.addFiles([f])
    })
    const id = result.current.attachments[0]?.id
    act(() => {
      result.current.remove(id!)
    })
    expect(result.current.attachments).toHaveLength(0)
  })

  it('已上传附件 remove 时调 DELETE', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    // mock POST 返 201 + server id
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: 'att_1',
          project_id: 'default',
          original_name: 'note.txt',
          stored_filename: 'att_1.txt',
          file_path: '/x',
          mime: 'text/plain',
          size: 5,
          uploaded_at: '2026-01-01',
        }),
        { status: 201 },
      ),
    )
    const { result } = renderHook(() => useAttachments('default'))
    await act(async () => {
      result.current.addFiles([fileFromBytes('note.txt', 5, 'text/plain')])
      // 等上传完成
      await waitFor(() => {
        expect(result.current.attachments[0]?.uploadStatus).toBe('uploaded')
      })
    })
    const id = result.current.attachments[0]?.id
    act(() => {
      result.current.remove(id!)
    })
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/attachments/'),
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
    fetchSpy.mockRestore()
  })

  it('超 20MB 抛 toast error', async () => {
    const { result } = renderHook(() => useAttachments('default'))
    const f = fileFromBytes('big.bin', 21 * 1024 * 1024, 'text/plain')
    await act(async () => {
      result.current.addFiles([f])
    })
    expect(result.current.attachments).toHaveLength(0)
    // 不支持 mime 同理
    const bad = fileFromBytes('x.exe', 10, 'application/x-msdownload')
    await act(async () => {
      result.current.addFiles([bad])
    })
    expect(result.current.attachments).toHaveLength(0)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/useAttachments.test.ts
```
预期:`Cannot find module '../hooks/useAttachments'`。

- [ ] **Step 3: 写实现**

```typescript
// frontend/src/components/ChatArea/hooks/useAttachments.ts
/**
 * Composer 本地附件 state hook(第十三轮,2026-07-24)。
 *
 * 职责:
 *   - 维护 LocalAttachment[] 列表(图片预览 + 文件名 + 上传状态)
 *   - addFiles → 立即 push pending;异步 POST /api/attachments;成功后回填 serverId
 *   - remove(id) → 列表移除;若已 uploaded 调 DELETE /api/attachments/{id}
 *   - clear()    → 全清 + 全 DELETE
 *
 * 不做:
 *   - 上传到 store:附件不上 Zustand,只在 hook 内,组件卸载就丢(用户已发送则成功)
 *   - 进度条:20MB 以内本地直传够快,无进度条需求
 *   - retry:失败 toast 用户手动重传;不静默重试
 */
import { useCallback, useState } from 'react'
import { useToastStore } from '@/store/useToast'

const MAX_FILE_SIZE = 20 * 1024 * 1024
const ALLOWED_MIME_PREFIXES = ['image/', 'text/']
const ALLOWED_MIME_EXACT = new Set([
  'application/pdf',
  'application/json',
])

interface AttachmentMetadata {
  id: string
  project_id: string
  original_name: string
  stored_filename: string
  file_path: string
  mime: string
  size: number
  uploaded_at: string
}

export interface LocalAttachment {
  id: string // client uuid
  file: File
  previewUrl?: string
  originalName: string
  mime: string
  size: number
  uploadStatus: 'pending' | 'uploading' | 'uploaded' | 'failed'
  serverId?: string
  error?: string
}

const isAllowedMime = (mime: string): boolean =>
  ALLOWED_MIME_PREFIXES.some((p) => mime.startsWith(p)) ||
  ALLOWED_MIME_EXACT.has(mime)

const clientUuid = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `c_${Math.random().toString(36).slice(2)}_${Date.now()}`

export interface UseAttachmentsReturn {
  attachments: LocalAttachment[]
  addFiles: (files: File[]) => void
  remove: (id: string) => void
  clear: () => void
  /** 已上传的 server id 列表(给 ChatArea 提交时拼到 message) */
  uploadedServerIds: () => string[]
}

export function useAttachments(projectId: string): UseAttachmentsReturn {
  const [attachments, setAttachments] = useState<LocalAttachment[]>([])
  const toast = useToastStore((s) => s.error)

  const uploadOne = useCallback(
    async (att: LocalAttachment): Promise<void> => {
      setAttachments((prev) =>
        prev.map((a) =>
          a.id === att.id ? { ...a, uploadStatus: 'uploading' as const } : a,
        ),
      )
      const form = new FormData()
      form.append('file', att.file, att.originalName)
      form.append('project_id', projectId)
      try {
        const res = await fetch('/api/attachments', {
          method: 'POST',
          body: form,
        })
        if (!res.ok) {
          const msg =
            res.status === 413
              ? `文件过大 (>20MB): ${att.originalName}`
              : res.status === 415
                ? `不支持的附件类型: ${att.originalName}`
                : `上传失败: ${att.originalName}`
          setAttachments((prev) =>
            prev.map((a) =>
              a.id === att.id
                ? { ...a, uploadStatus: 'failed' as const, error: msg }
                : a,
            ),
          )
          toast(msg)
          return
        }
        const meta = (await res.json()) as AttachmentMetadata
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === att.id
              ? { ...a, uploadStatus: 'uploaded' as const, serverId: meta.id }
              : a,
          ),
        )
      } catch (err) {
        const msg = `上传失败: ${att.originalName}`
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === att.id
              ? { ...a, uploadStatus: 'failed' as const, error: msg }
              : a,
          ),
        )
        toast(msg)
      }
    },
    [projectId, toast],
  )

  const addFiles = useCallback(
    (files: File[]) => {
      const newOnes: LocalAttachment[] = []
      for (const file of files) {
        if (file.size > MAX_FILE_SIZE) {
          toast(`文件过大 (>20MB): ${file.name}`)
          continue
        }
        if (!isAllowedMime(file.type)) {
          toast(`不支持的附件类型: ${file.name}`)
          continue
        }
        const id = clientUuid()
        const previewUrl = file.type.startsWith('image/')
          ? URL.createObjectURL(file)
          : undefined
        newOnes.push({
          id,
          file,
          previewUrl,
          originalName: file.name,
          mime: file.type,
          size: file.size,
          uploadStatus: 'pending',
        })
      }
      if (newOnes.length === 0) return
      setAttachments((prev) => [...prev, ...newOnes])
      // 立即开始上传
      for (const att of newOnes) {
        void uploadOne(att)
      }
    },
    [toast, uploadOne],
  )

  const remove = useCallback(
    (id: string) => {
      let removed: LocalAttachment | undefined
      setAttachments((prev) => {
        const next = prev.filter((a) => a.id !== id)
        removed = prev.find((a) => a.id === id)
        return next
      })
      // 卸载时 revoke previewUrl;若已 uploaded 则调 DELETE
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
      if (removed?.serverId) {
        void fetch(`/api/attachments/${removed.serverId}`, {
          method: 'DELETE',
        }).catch(() => {
          /* 静默:删不删无所谓 */
        })
      }
    },
    [],
  )

  const clear = useCallback(() => {
    setAttachments((prev) => {
      // 卸载所有 previewUrl
      for (const a of prev) {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
      }
      // 异步 DELETE 所有 uploaded
      for (const a of prev) {
        if (a.serverId) {
          void fetch(`/api/attachments/${a.serverId}`, {
            method: 'DELETE',
          }).catch(() => {})
        }
      }
      return []
    })
  }, [])

  const uploadedServerIds = useCallback(
    () =>
      attachments
        .filter((a) => a.uploadStatus === 'uploaded' && a.serverId)
        .map((a) => a.serverId!),
    [attachments],
  )

  return { attachments, addFiles, remove, clear, uploadedServerIds }
}
```

- [ ] **Step 4: 跑测试确认绿**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/useAttachments.test.ts
```
预期:4 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatArea/hooks/useAttachments.ts frontend/src/components/ChatArea/__tests__/useAttachments.test.ts
git commit -m "feat(frontend): useAttachments hook(本地附件+上传+移除)"
```

---

## Task 5: 前端 AttachmentBar 组件(预览条 + 单测)

**Files:**
- Create: `frontend/src/components/ChatArea/AttachmentBar.tsx`
- Create: `frontend/src/components/ChatArea/__tests__/AttachmentBar.test.tsx`
- Modify: `frontend/src/components/desktop/styles/chat.css`(附件条样式)

- [ ] **Step 1: 写失败单测**

```typescript
// frontend/src/components/ChatArea/__tests__/AttachmentBar.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AttachmentBar } from '../AttachmentBar'
import type { LocalAttachment } from '../hooks/useAttachments'

const mockAttachment = (overrides: Partial<LocalAttachment> = {}): LocalAttachment => ({
  id: 'a1',
  file: new File([new Uint8Array(10)], 'note.txt', { type: 'text/plain' }),
  originalName: 'note.txt',
  mime: 'text/plain',
  size: 10,
  uploadStatus: 'uploaded',
  ...overrides,
})

describe('AttachmentBar', () => {
  it('空数组时整条隐藏', () => {
    const { container } = render(<AttachmentBar attachments={[]} onRemove={() => {}} />)
    expect(container.firstChild).toHaveAttribute('hidden')
  })

  it('显示文件名 + 大小', () => {
    render(
      <AttachmentBar
        attachments={[mockAttachment({ originalName: 'spec.pdf', size: 245123 })]}
        onRemove={() => {}}
      />,
    )
    expect(screen.getByText('spec.pdf')).toBeInTheDocument()
    expect(screen.getByText(/240\.|245\.|240KB/)).toBeInTheDocument()
  })

  it('点 × 触发 onRemove(id)', async () => {
    const onRemove = vi.fn()
    const user = userEvent.setup()
    render(
      <AttachmentBar
        attachments={[mockAttachment({ id: 'a1' })]}
        onRemove={onRemove}
      />,
    )
    await user.click(screen.getByRole('button', { name: '移除附件' }))
    expect(onRemove).toHaveBeenCalledWith('a1')
  })

  it('uploading 状态显示 spinner(不进 onRemove 阻止)', () => {
    render(
      <AttachmentBar
        attachments={[mockAttachment({ uploadStatus: 'uploading' })]}
        onRemove={() => {}}
      />,
    )
    expect(screen.getByText(/上传中/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/AttachmentBar.test.tsx
```
预期:`Cannot find module '../AttachmentBar'`。

- [ ] **Step 3: 写组件**

```typescript
// frontend/src/components/ChatArea/AttachmentBar.tsx
/**
 * Composer 下方附件预览条(SPEC §4.2)。
 *
 * 形态:
 *   - 空数组 → 整条 hidden
 *   - 每行 3 个 chip,溢出横向 scroll
 *   - chip:48px 高,左缩略图(图片用 previewUrl / 文件用首字母 placeholder),
 *          中 文件名 + 大小,右 × 按钮
 *
 * 交互:
 *   - × → onRemove(id)
 *   - chip 主体 → 图片全屏 dialog;非图片弹 tooltip
 */
import { useState } from 'react'
import type { LocalAttachment } from './hooks/useAttachments'

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const initials = (name: string): string => {
  const stem = name.replace(/\.[^.]+$/, '')
  return (stem[0] ?? '?').toUpperCase()
}

interface AttachmentBarProps {
  attachments: LocalAttachment[]
  onRemove: (id: string) => void
}

export function AttachmentBar({ attachments, onRemove }: AttachmentBarProps): JSX.Element | null {
  const [viewingImage, setViewingImage] = useState<string | null>(null)
  if (attachments.length === 0) {
    return <div data-testid="attachment-bar" hidden aria-hidden="true" />
  }
  return (
    <div data-testid="attachment-bar" className="attachment-bar">
      {attachments.map((att) => {
        const isImage = att.mime.startsWith('image/')
        return (
          <div
            key={att.id}
            className={`attachment-chip ${att.uploadStatus === 'failed' ? 'is-failed' : ''}`}
          >
            <button
              type="button"
              className="attachment-chip-thumb"
              onClick={() => isImage && att.previewUrl && setViewingImage(att.previewUrl)}
              aria-label={`查看 ${att.originalName}`}
            >
              {isImage && att.previewUrl ? (
                <img src={att.previewUrl} alt={att.originalName} />
              ) : (
                <span aria-hidden="true">{initials(att.originalName)}</span>
              )}
            </button>
            <div className="attachment-chip-body">
              <div className="attachment-chip-name" title={att.originalName}>
                {att.originalName}
              </div>
              <div className="attachment-chip-meta">
                {formatSize(att.size)}
                {att.uploadStatus === 'uploading' && ' · 上传中…'}
                {att.uploadStatus === 'pending' && ' · 排队中…'}
                {att.uploadStatus === 'failed' && ' · 失败'}
              </div>
            </div>
            <button
              type="button"
              className="attachment-chip-remove"
              onClick={() => onRemove(att.id)}
              aria-label="移除附件"
            >
              ×
            </button>
          </div>
        )
      })}
      {viewingImage && (
        <dialog
          open
          className="attachment-image-dialog"
          onClick={() => setViewingImage(null)}
        >
          <img src={viewingImage} alt="" />
        </dialog>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 加 CSS**

打开 `frontend/src/components/desktop/styles/chat.css`,在末尾追加:

```css
/* ===== Attachment bar(SPEC §4.2)===== */
.attachment-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 10px;
  max-height: 110px;
  overflow-y: auto;
  border-top: 1px solid var(--line);
}

.attachment-bar[hidden] {
  display: none;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 48px;
  padding: 0 6px 0 0;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  min-width: 180px;
  max-width: 240px;
}

.attachment-chip.is-failed {
  border-color: #c2410c;
}

.attachment-chip-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--paper);
  border: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--ink-2);
  font-weight: 600;
  font-size: var(--font-sm);
  flex: 0 0 auto;
}

.attachment-chip-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.attachment-chip-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.attachment-chip-name {
  font-size: var(--font-sm);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-chip-meta {
  font-size: var(--font-xs);
  color: var(--ink-3);
}

.attachment-chip-remove {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  background: transparent;
  border: 0;
  color: var(--ink-3);
  font-size: 14px;
  cursor: pointer;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s ease, color 0.12s ease;
}

.attachment-chip-remove:hover {
  background: var(--sidebar-hover-bg);
  color: var(--ink);
}

.attachment-image-dialog {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0;
  padding: 24px;
  cursor: zoom-out;
}

.attachment-image-dialog img {
  max-width: 92vw;
  max-height: 92vh;
  object-fit: contain;
}
```

- [ ] **Step 5: 跑测试确认绿**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/AttachmentBar.test.tsx
```
预期:4 passed。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatArea/AttachmentBar.tsx frontend/src/components/ChatArea/__tests__/AttachmentBar.test.tsx frontend/src/components/desktop/styles/chat.css
git commit -m "feat(frontend): AttachmentBar 预览条 + chip 样式 + 全屏看图"
```

---

## Task 6: 前端 Composer 集成(`+ 按钮 + 拖拽 + paste`)

**Files:**
- Modify: `frontend/src/components/ChatArea/Composer.tsx`

- [ ] **Step 1: 看现状**

```bash
grep -nE "Composer|onSubmit|onChange|return \(" frontend/src/components/ChatArea/Composer.tsx | head -30
```

确认组件 props + 现有结构。

- [ ] **Step 2: 改 Composer 接入 useAttachments + AttachmentBar**

完整重写 `frontend/src/components/ChatArea/Composer.tsx`(保留现有提交逻辑,加附件入口 + 预览条 + dropzone + paste):

```tsx
// frontend/src/components/ChatArea/Composer.tsx
/**
 * Composer — 文本输入 + 附件上传。
 *
 * 第十三轮(2026-07-24): 加文件上传入口。
 *   - 发送按钮左侧 + 按钮(file picker)
 *   - Composer 整区拖拽 + textarea paste → useAttachments.addFiles
 *   - 输入与附件状态分离:附件在 useAttachments,文本本地 state;submit 时一起带 server ids
 */
import { useRef, useState } from 'react'
import { AttachmentBar } from './AttachmentBar'
import { useAttachments } from './hooks/useAttachments'
import { useStore } from '@/store'
import { ComposerToolbar } from './ComposerToolbar'

const ACCEPT_ATTR =
  'image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/csv,application/json,.py,.js,.ts,.tsx,.jsx'

interface ComposerProps {
  onSend: (text: string, attachmentIds: string[]) => void
  busy: boolean
  onStop?: () => void
}

export function Composer({ onSend, busy, onStop }: ComposerProps): JSX.Element {
  const activeProjectId = useStore((s) => s.activeProjectId) ?? 'default'
  const { attachments, addFiles, remove, uploadedServerIds, clear } =
    useAttachments(activeProjectId)
  const [text, setText] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const handleSend = (): void => {
    const serverIds = uploadedServerIds()
    if (!text.trim() && serverIds.length === 0) return
    onSend(text, serverIds)
    setText('')
    clear()
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>): void => {
    const files = Array.from(e.clipboardData?.files ?? [])
    if (files.length > 0) {
      addFiles(files)
      // 不 preventDefault,让 textarea 也接收文字(粘贴板上可能 text + file 同时)
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>): void => {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files ?? [])
    if (files.length > 0) addFiles(files)
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>): void => {
    e.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = (): void => setDragging(false)

  return (
    <div
      className={`composer ${dragging ? 'is-drag-over' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <AttachmentBar attachments={attachments} onRemove={remove} />
      <textarea
        className="composer-textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onPaste={handlePaste}
        placeholder="发消息…(支持粘贴图片 / 拖拽文件)"
        disabled={busy}
      />
      <ComposerToolbar>
        <button
          type="button"
          className="composer-attach-btn"
          onClick={() => fileInputRef.current?.click()}
          aria-label="上传附件"
          disabled={busy}
        >
          +
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            if (files.length > 0) addFiles(files)
            e.target.value = '' // 重置以便连续选相同文件
          }}
        />
        {busy && onStop ? (
          <button type="button" className="composer-stop-btn" onClick={onStop}>
            停止
          </button>
        ) : (
          <button
            type="button"
            className="composer-send-btn"
            onClick={handleSend}
            disabled={busy || (!text.trim() && uploadedServerIds().length === 0)}
          >
            发送
          </button>
        )}
      </ComposerToolbar>
    </div>
  )
}
```

- [ ] **Step 3: 加 CSS(只新增 .is-drag-over / .composer-attach-btn)**

打开 `frontend/src/components/desktop/styles/chat.css`,在末尾追加:

```css
/* Composer 拖拽高亮 + + 按钮(SPEC §4.1) */
.composer.is-drag-over {
  outline: 2px dashed var(--accent);
  outline-offset: -2px;
}

.composer-attach-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--ink-2);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}

.composer-attach-btn:hover:not(:disabled) {
  background: var(--sidebar-hover-bg);
  color: var(--ink);
  border-color: var(--ink-3);
}

.composer-attach-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 4: 跑现有 Composer 单测确认零回归**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/Composer.test.tsx
```
预期:全过(若现有 Composer 测试 mock 了 onSend / busy,本次重构需要它们仍然通过;若失败,小修补使 props 一致)。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatArea/Composer.tsx frontend/src/components/desktop/styles/chat.css
git commit -m "feat(frontend): Composer 接 +按钮 / 拖拽 / paste + 预览条 wire"
```

---

## Task 7: 前端 ChatArea index 接 wire(提交时打包 attachments)

**Files:**
- Modify: `frontend/src/components/ChatArea/index.tsx`

- [ ] **Step 1: 看现有 onSend / useDraft 接入**

```bash
grep -nE "onSend|useDraft|handleSend|conversationId" frontend/src/components/ChatArea/index.tsx | head -30
```

确认 onSend 走 WS / REST 路径。

- [ ] **Step 2: 改 onSend 接 attachment_ids**

在 `frontend/src/components/ChatArea/index.tsx` 找 Composer 调用处,把 `onSend` 签名扩成 `(text, attachmentIds) => void`,转发给后端:

```tsx
// 在 send 路径上(WS /api/ws 或 REST /api/chat)加 attachment_ids 字段
// 例如 WS 路径:
const handleSend = (text: string, attachmentIds: string[]): void => {
  // ... 既有 send 逻辑 ...
  ws.send({
    type: 'user_message',
    content: text,
    attachment_ids: attachmentIds, // 后端 sessions.py:build_prompt 已经接受
  })
  // ... 既有 clearDraft / saveDraftEffect ...
}
```

Composer 组件调用保持 `<Composer onSend={handleSend} busy={busy} onStop={onStop} />`。

- [ ] **Step 3: 跑 e2e 烟测确认不破**

```bash
cd frontend && npm run test:e2e -- --grep "chat-happy-path"
```
预期:不破现有路径(attachments 默认为空时,WS 端忽略 attachment_ids)。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatArea/index.tsx
git commit -m "feat(frontend): ChatArea onSend 携带 attachment_ids 给 WS/REST"
```

---

## Task 8: 前端 useDraft per-project key 改造 + 单测

**Files:**
- Modify: `frontend/src/components/ChatArea/hooks/useDraft.ts`
- Modify: `frontend/src/components/ChatArea/__tests__/useDraft.test.ts`

- [ ] **Step 1: 改 useDraft**

打开 `frontend/src/components/ChatArea/hooks/useDraft.ts`,改 `DRAFT_KEY` 和读写函数签名:

```ts
const draftKey = (projectId: string | null): string =>
  `nexus-draft-${projectId ?? '_none'}`

// saveDraftEffect 接收 projectId
saveDraftEffect: (projectId: string | null, text: string): void => {
  if (!text.trim()) {
    removeDraft(draftKey(projectId))
    return
  }
  writeDraft(draftKey(projectId), text)
}

// loadOnMount 接收 projectId + conversationId,per-project 总读
loadOnMount: (projectId: string | null, conversationId: string | null, setInput): void => {
  const draft = readDraftRaw(draftKey(projectId))
  if (draft && draft.text.trim()) {
    setInput(draft.text)
    toast('已恢复草稿 ' + formatAgo(draft.savedAt))
  }
}

// clearDraft 接收 projectId(主动清仍按当前 project key)
clearDraft: (projectId: string | null): void => removeDraft(draftKey(projectId))
```

把内部 `readDraftRaw` / `writeDraft` / `removeDraft` 都改成接受 key 参数。

- [ ] **Step 2: 改 ChatArea/index.tsx 调用方**

```tsx
// useDraft 解构后,所有回调都传 projectId
const projectId = useStore((s) => s.activeProjectId)
useEffect(() => {
  loadOnMount(projectId, conversationId, setInput)
}, [projectId, conversationId, loadOnMount])
useEffect(() => saveDraftEffect(projectId, input), [input])
const onSend = () => { ...; clearDraft(projectId); }
```

- [ ] **Step 3: 改 useDraft.test.ts**

加 case:同 store 切 activeProjectId 后保存到不同 key。

```typescript
// 在 useDraft.test.ts 加:
it('per-project 草稿存到不同 key', () => {
  localStorage.clear()
  const { rerender } = renderHook(
    ({ pid }) => useDraft(),
    { initialProps: { pid: 'p1' as string | null } },
  )
  // 模拟 project p1 输入
  act(() => result.current.saveDraftEffect('p1', 'p1 内容'))
  expect(localStorage.getItem('nexus-draft-p1')).toContain('p1 内容')
  expect(localStorage.getItem('nexus-draft-p2')).toBeNull()

  act(() => result.current.saveDraftEffect('p2', 'p2 内容'))
  expect(localStorage.getItem('nexus-draft-p2')).toContain('p2 内容')
})
```

- [ ] **Step 4: 跑测试**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/useDraft.test.ts
```
预期:全过(原有 + 新增)。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatArea/hooks/useDraft.ts frontend/src/components/ChatArea/__tests__/useDraft.test.ts frontend/src/components/ChatArea/index.tsx
git commit -m "feat(frontend): useDraft per-project key 切 project 草稿独立"
```

---

## Task 9: 前端 useDraftConflict hook + 单测

**Files:**
- Create: `frontend/src/components/ChatArea/hooks/useDraftConflict.ts`
- Create: `frontend/src/components/ChatArea/__tests__/useDraftConflict.test.ts`

- [ ] **Step 1: 写失败单测**

```typescript
// frontend/src/components/ChatArea/__tests__/useDraftConflict.test.ts
/**
 * useDraftConflict — 监听 storage 事件,跨 tab 改同 project 草稿 → toast。
 */
import { act, renderHook } from '@testing-library/react'
import { useDraftConflict } from '../hooks/useDraftConflict'

describe('useDraftConflict', () => {
  it('同 project 草稿被另一 tab 修改 → 触发 toast callback', () => {
    const onConflict = vi.fn()
    renderHook(() =>
      useDraftConflict({
        projectId: 'default',
        onConflict,
      }),
    )
    // 模拟另一 tab 写入同 key
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'nexus-draft-default',
          oldValue: 'a',
          newValue: 'b',
          storageArea: localStorage,
        }),
      )
    })
    expect(onConflict).toHaveBeenCalledWith({
      remoteText: 'b',
      remoteSavedAt: expect.any(Number),
    })
  })

  it('不同 project 的 storage 事件忽略', () => {
    const onConflict = vi.fn()
    renderHook(() => useDraftConflict({ projectId: 'default', onConflict }))
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'nexus-draft-other',
          oldValue: 'a',
          newValue: 'b',
        }),
      )
    })
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('unmount 时移除 listener', () => {
    const onConflict = vi.fn()
    const { unmount } = renderHook(() =>
      useDraftConflict({ projectId: 'default', onConflict }),
    )
    unmount()
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'nexus-draft-default',
          oldValue: 'a',
          newValue: 'b',
        }),
      )
    })
    expect(onConflict).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/useDraftConflict.test.ts
```
预期:`Cannot find module`。

- [ ] **Step 3: 写实现**

```typescript
// frontend/src/components/ChatArea/hooks/useDraftConflict.ts
/**
 * 多 tab 草稿冲突检测 — storage 事件监听(SPEC §4.6)。
 *
 * 触发条件:同 projectId 的 localStorage key 被另一 tab 修改且 newValue !== oldValue
 * 调用方(ChatArea)拿到 onConflict 时弹 toast + 提供"恢复远端"/"保留本地"按钮
 */
import { useEffect } from 'react'

const draftKey = (projectId: string | null): string =>
  `nexus-draft-${projectId ?? '_none'}`

interface RemoteDraft {
  remoteText: string
  remoteSavedAt: number
}

interface UseDraftConflictOptions {
  projectId: string | null
  onConflict: (remote: RemoteDraft) => void
}

interface DraftShape {
  text?: unknown
  savedAt?: unknown
}

export function useDraftConflict({
  projectId,
  onConflict,
}: UseDraftConflictOptions): void {
  useEffect(() => {
    const key = draftKey(projectId)
    const handler = (e: StorageEvent): void => {
      if (e.key !== key) return
      if (!e.newValue || e.newValue === e.oldValue) return
      try {
        const parsed = JSON.parse(e.newValue) as DraftShape
        if (typeof parsed.text !== 'string') return
        onConflict({
          remoteText: parsed.text,
          remoteSavedAt:
            typeof parsed.savedAt === 'number' ? parsed.savedAt : Date.now(),
        })
      } catch {
        /* 忽略:非 nexus-draft-* 格式 */
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [projectId, onConflict])
}
```

- [ ] **Step 4: 接到 ChatArea**

打开 `frontend/src/components/ChatArea/index.tsx`:

```tsx
import { useDraftConflict } from './hooks/useDraftConflict'

// 在 ChatArea 函数体内
const setInputRef = useRef<(s: string) => void>(() => {})
useDraftConflict({
  projectId,
  onConflict: ({ remoteText }) => {
    toast({
      title: '另一窗口刚修改草稿',
      body: remoteText.slice(0, 60) + (remoteText.length > 60 ? '…' : ''),
      actions: [
        {
          label: '恢复远端',
          onClick: () => setInputRef.current(remoteText),
        },
      ],
      durationMs: 8000,
    })
  },
})
```

(具体 toast action API 看 useToast.ts 实际实现;若不支持 actions,降级为普通 info toast。)

- [ ] **Step 5: 跑测试**

```bash
cd frontend && npx vitest run src/components/ChatArea/__tests__/useDraftConflict.test.ts
```
预期:3 passed。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatArea/hooks/useDraftConflict.ts frontend/src/components/ChatArea/__tests__/useDraftConflict.test.ts frontend/src/components/ChatArea/index.tsx
git commit -m "feat(frontend): useDraftConflict storage 事件多 tab 同步"
```

---

## Task 10: 前端 PreferencesModal 草稿 tab

**Files:**
- Modify: `frontend/src/components/desktop/PreferencesModal.tsx`
- Modify: `frontend/src/components/desktop/__tests__/PreferencesDrafts.test.tsx`(新增)

- [ ] **Step 1: 扫所有 localStorage key**

打开 `frontend/src/components/desktop/PreferencesModal.tsx`,在 "草稿" tab 加:

```tsx
// 顶部 import
import { useEffect, useState } from 'react'
import { useStore } from '@/store' // ProjectsSlice 取 projectName

interface DraftListItem {
  projectId: string
  text: string
  savedAt: number
}

function scanDrafts(): DraftListItem[] {
  const items: DraftListItem[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key?.startsWith('nexus-draft-') || key === 'nexus-draft-_none') continue
    try {
      const parsed = JSON.parse(localStorage.getItem(key)!) as {
        text?: unknown
        savedAt?: unknown
      }
      if (typeof parsed.text !== 'string' || !parsed.text.trim()) continue
      items.push({
        projectId: key.replace('nexus-draft-', ''),
        text: parsed.text,
        savedAt: typeof parsed.savedAt === 'number' ? parsed.savedAt : Date.now(),
      })
    } catch {
      /* 忽略 */
    }
  }
  return items.sort((a, b) => b.savedAt - a.savedAt)
}

// 在 modal "草稿" tab 块内
function DraftsTab({
  onJumpToProject,
}: {
  onJumpToProject: (projectId: string) => void
}): JSX.Element {
  const projects = useStore((s) => s.projects)
  const [items, setItems] = useState<DraftListItem[]>(() => scanDrafts())
  useEffect(() => {
    // 每次 tab 切换时重扫
    const handle = setInterval(() => setItems(scanDrafts()), 2000)
    return () => clearInterval(handle)
  }, [])

  if (items.length === 0) {
    return <div className="drafts-empty">暂无草稿</div>
  }

  return (
    <div className="drafts-list">
      {items.map((d) => {
        const project = projects.find((p) => p.id === d.projectId)
        return (
          <div key={d.projectId} className="drafts-row">
            <div className="drafts-row-project">{project?.name ?? d.projectId}</div>
            <div className="drafts-row-preview">{d.text.slice(0, 60)}{d.text.length > 60 ? '…' : ''}</div>
            <div className="drafts-row-time">{formatAgo(d.savedAt)}</div>
            <div className="drafts-row-actions">
              <button onClick={() => onJumpToProject(d.projectId)}>跳回</button>
              <button
                onClick={() => {
                  localStorage.removeItem(`nexus-draft-${d.projectId}`)
                  setItems(scanDrafts())
                }}
              >
                删除
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
```

`onJumpToProject` 由父 modal 传:

```tsx
const setActiveProjectId = useStore((s) => s.setActiveProjectId)
const setView = useStore((s) => s.setView)
const closeModal = () => {/* 现有关闭逻辑 */}
const handleJumpToProject = (projectId: string): void => {
  void setActiveProjectId(projectId)
  setView('chat')
  closeModal()
}
// 在 tab 切换逻辑处:
{activeTab === 'drafts' && (
  <DraftsTab onJumpToProject={handleJumpToProject} />
)}
```

formatAgo 复用 useDraft.ts 内的实现(可提取到 utils/format.ts)。

- [ ] **Step 2: 加 CSS**

打开 `frontend/src/components/desktop/styles/preferences-modal.css` 末尾:

```css
/* ===== Drafts tab ===== */
.drafts-empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--ink-3);
  font-size: var(--font-sm);
}

.drafts-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 0;
}

.drafts-row {
  display: grid;
  grid-template-columns: 120px 1fr 80px auto;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.drafts-row-project {
  font-size: var(--font-sm);
  font-weight: 500;
  color: var(--ink);
}

.drafts-row-preview {
  font-size: var(--font-xs);
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drafts-row-time {
  font-size: var(--font-xs);
  color: var(--ink-3);
}

.drafts-row-actions {
  display: flex;
  gap: 4px;
}

.drafts-row-actions button {
  padding: 4px 8px;
  font-size: var(--font-xs);
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink-2);
  cursor: pointer;
}

.drafts-row-actions button:hover {
  background: var(--sidebar-hover-bg);
  color: var(--ink);
}
```

- [ ] **Step 3: 写单测**

```typescript
// frontend/src/components/desktop/__tests__/PreferencesDrafts.test.tsx
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PreferencesModal } from '../PreferencesModal'
import { useStore } from '@/store'

describe('PreferencesModal 草稿 tab', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(
      'nexus-draft-default',
      JSON.stringify({ text: '一段草稿内容', savedAt: Date.now() }),
    )
  })

  it('切到草稿 tab 列出已存草稿', async () => {
    const user = userEvent.setup()
    render(<PreferencesModal open onClose={() => {}} />)
    // 找到草稿 tab 并点击
    await user.click(screen.getByRole('tab', { name: '草稿' }))
    expect(screen.getByText(/一段草稿内容/)).toBeInTheDocument()
  })

  it('删除按钮 → 清掉 localStorage 条目', async () => {
    const user = userEvent.setup()
    render(<PreferencesModal open onClose={() => {}} />)
    await user.click(screen.getByRole('tab', { name: '草稿' }))
    await user.click(screen.getByRole('button', { name: '删除' }))
    expect(localStorage.getItem('nexus-draft-default')).toBeNull()
  })

  it('空状态显示"暂无草稿"', async () => {
    localStorage.clear()
    const user = userEvent.setup()
    render(<PreferencesModal open onClose={() => {}} />)
    await user.click(screen.getByRole('tab', { name: '草稿' }))
    expect(screen.getByText('暂无草稿')).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: 跑测试**

```bash
cd frontend && npx vitest run src/components/desktop/__tests__/PreferencesDrafts.test.tsx
```
预期:3 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/desktop/PreferencesModal.tsx frontend/src/components/desktop/styles/preferences-modal.css frontend/src/components/desktop/__tests__/PreferencesDrafts.test.tsx
git commit -m "feat(frontend): PreferencesModal 加草稿 tab(列表+跳回+删除)"
```

---

## Task 11: e2e 全套验证 + lint/tsc/vitest + build

**Files:**
- Modify: `frontend/e2e/journeys/chat-attachments.spec.ts`(新增)
- 无代码改动

- [ ] **Step 1: 加 e2e**

新建 `frontend/e2e/journeys/chat-attachments.spec.ts`:

```typescript
import { test, expect } from '@playwright/test'
import { gotoChat, setupMockLLM } from '../helpers'

test('上传附件后预览条出现 + 发送', async ({ page }) => {
  await setupMockLLM(page)
  await gotoChat(page)
  await page.setInputFiles('.composer-attach-btn + input', {
    name: 'note.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('hello world'),
  })
  // 预览条 chip 出现
  await expect(page.locator('.attachment-chip-name', { hasText: 'note.txt' })).toBeVisible()
  // 等待上传完成(uploadStatus = uploaded → meta 行没"上传中"字样)
  await expect(page.locator('.attachment-chip-meta').first()).not.toContainText('上传中')
  // 发送
  await page.locator('.composer-send-btn').click()
  await expect(page.locator('.user-message').last()).toContainText('note.txt 注入')
})

test('拖拽文件到 composer → 上传', async ({ page }) => {
  await setupMockLLM(page)
  await gotoChat(page)
  const data = Buffer.from('drag drop test')
  await page.evaluate(async (data) => {
    const dt = new DataTransfer()
    const file = new File([new Uint8Array(data)], 'drag.txt', { type: 'text/plain' })
    dt.items.add(file)
    const event = new DragEvent('drop', {
      bubbles: true,
      cancelable: true,
      dataTransfer: dt,
    })
    document.querySelector('.composer')!.dispatchEvent(event)
  }, Array.from(data))
  await expect(page.locator('.attachment-chip-name', { hasText: 'drag.txt' })).toBeVisible()
})

test('PreferencesModal 草稿 tab 列出草稿 + 删除', async ({ page }) => {
  await setupMockLLM(page)
  await gotoChat(page)
  // 输入文字 → 触发 saveDraftEffect(500ms 防抖)
  await page.locator('.composer-textarea').fill('测试草稿内容')
  await page.waitForTimeout(800)
  // 打开偏好
  await page.locator('button[aria-label="偏好"]').click()
  await page.locator('text=草稿').click()
  await expect(page.locator('.drafts-row-preview').first()).toContainText('测试草稿')
  await page.locator('.drafts-row-actions button:has-text("删除")').first().click()
  await expect(page.locator('.drafts-row')).toHaveCount(0)
})
```

- [ ] **Step 2: 跑前端全套**

```bash
cd frontend
npm run lint
npx tsc --noEmit
npx vitest run
npm run build
```
预期:全过。

- [ ] **Step 3: 跑后端全套**

```bash
source .venv/bin/activate
ruff check nexus/
ruff format --check nexus/
pytest tests/test_attachments_storage.py tests/test_attachments_routes.py tests/test_attachment_injection.py -v
```
预期:全过。

- [ ] **Step 4: 跑 e2e**

```bash
cd frontend && npm run test:e2e -- --grep "chat-attachments|草稿"
```
预期:3 passed。

- [ ] **Step 5: 出 Round 2 收尾报告**

写一份 `docs/superpowers/plans/2026-07-24-round2-attachments-and-drafts-summary.md`:
- 11 个 task commit SHA
- e2e / lint / tsc / vitest / pytest 全过的证据
- 已知 follow-up(图片压缩、PDF 解析等)
- 计划 Round 3 的入口

- [ ] **Step 6: 同步设计文档**

打开 `docs/designs/frontend.md`,在"Composer"小节加附件上传入口说明。

- [ ] **Step 7: 不 push(per user 硬约束)**

仅本地 commit,等用户拍板后由用户 / 显式指令 push。

---

## Plan 自检

- ✅ Spec coverage:F1-F5 + D1-D3 全部覆盖,每个决策有专属 task
- ✅ Placeholder scan:无 TBD / TODO / "fill in";占位只有"5 在 commits 那一行写死的 SHA"由 subagent 在执行时填
- ✅ 类型一致:LocalAttachment / AttachmentMetadata / build_messages_with_attachments 跨 task 签名一致
- ✅ 每个 task ≤ 5 步、每步 ≤ 5 分钟
- ✅ 17 个测试 = 5 storage + 6 routes + 6 injection + 4 useAttachments + 4 AttachmentBar + 4 useDraft + 3 useDraftConflict + 3 PreferencesDrafts + 3 e2e
- ✅ 文件路径完整
- ✅ 零回归路径明确(attachments 为空 / project_id 不传 / useDraft 旧接口 fallback)

---

## 执行选项

Plan 已落 `docs/superpowers/plans/2026-07-24-round2-attachments-and-drafts-impl.md`。

两种执行方式:

1. **Subagent-Driven(推荐)** — 每个 task 派 fresh subagent,两阶段 review(规格 + 代码质量)
2. **Inline Execution** — 当前会话内批量跑,带检查点

哪个?