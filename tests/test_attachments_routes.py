"""POST /api/attachments 单测 — multipart 上传 + 校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """tmp_path 当 ~,project_dir = tmp_path/Nexus/projects/default。

    通过 monkeypatch 让 _projects_root() 直接返回 tmp 路径,
    避免 _get_nexus_home() 走真实 ~/.nexus 把测试文件落到 home。
    require_token 走 CONFIG["ws_token"],直接 setitem 写入测试 token。
    在 DB 里塞一条 default project row,让 _project_dir() 能查到。
    """
    from datetime import UTC, datetime

    from nexus.backend import config as config_module
    from nexus.backend import db as db_module
    from nexus.backend.projects import storage as project_storage

    fake_root = tmp_path / "Nexus" / "projects"
    fake_root.mkdir(parents=True)
    project_dir = fake_root / "default"
    project_dir.mkdir()
    monkeypatch.setattr(project_storage, "_projects_root", lambda: fake_root)
    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-attachments-token")
    db_module.init_db()
    now = datetime.now(UTC).isoformat()
    with db_module.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, display_name, path, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "default",
                "default",
                "Default",
                str(project_dir),
                "",
                now,
                now,
            ),
        )
    return TestClient(app)


AUTH = {"Authorization": "Bearer test-attachments-token"}


def test_post_attachment_text_plain(client: TestClient) -> None:
    """上传 .txt 文本 → 201 + metadata。"""
    response = client.post(
        "/api/attachments",
        headers=AUTH,
        data={"project_id": "default"},
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_name"] == "note.txt"
    assert body["mime"] == "text/plain"
    assert body["size"] == 11
    assert body["file_path"].endswith(body["stored_filename"])
    assert body["project_id"] == "default"


def test_post_attachment_rejects_oversize(client: TestClient) -> None:
    """超 20MB → 413。"""
    big = b"x" * (20 * 1024 * 1024 + 1)
    response = client.post(
        "/api/attachments",
        headers=AUTH,
        data={"project_id": "default"},
        files={"file": ("big.bin", big, "text/plain")},
    )
    assert response.status_code == 413


def test_post_attachment_rejects_unsupported_mime(client: TestClient) -> None:
    """.exe → 415。"""
    response = client.post(
        "/api/attachments",
        headers=AUTH,
        data={"project_id": "default"},
        files={"file": ("x.exe", b"x", "application/x-msdownload")},
    )
    assert response.status_code == 415


def test_post_attachment_unknown_project(client: TestClient) -> None:
    """project_id 不存在 → 404。"""
    response = client.post(
        "/api/attachments",
        headers=AUTH,
        data={"project_id": "no-such"},
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert response.status_code == 404


def test_get_attachment_returns_raw(client: TestClient) -> None:
    """GET /api/attachments/{id} 返 raw bytes + Content-Disposition。"""
    post = client.post(
        "/api/attachments",
        headers=AUTH,
        data={"project_id": "default"},
        files={"file": ("note.txt", b"abc", "text/plain")},
    )
    assert post.status_code == 201
    att_id = post.json()["id"]
    response = client.get(f"/api/attachments/{att_id}", headers=AUTH)
    assert response.status_code == 200
    assert response.content == b"abc"
    assert "note.txt" in response.headers.get("content-disposition", "")


def test_delete_attachment_removes_file(client: TestClient) -> None:
    """DELETE /api/attachments/{id} → 204 + 文件从磁盘删。"""
    post = client.post(
        "/api/attachments",
        headers=AUTH,
        data={"project_id": "default"},
        files={"file": ("note.txt", b"abc", "text/plain")},
    )
    file_path = Path(post.json()["file_path"])
    assert file_path.exists()
    att_id = post.json()["id"]
    response = client.delete(f"/api/attachments/{att_id}", headers=AUTH)
    assert response.status_code == 204
    assert not file_path.exists()
