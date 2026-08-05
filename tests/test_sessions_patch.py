"""PATCH /api/sessions/{id} 端点单测。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from nexus.backend import config as config_module
from nexus.backend import db
from nexus.backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离 DB + ws_token,跟 sessions.py router 的 require_token 对齐。

    复制 test_session_export.py / test_projects_api.py 模式:
    setenv + setitem(CONFIG["ws_token"]) 双保险,因 CONFIG 在模块加载时
    已绑定,setenv 仅影响后续读取,必须配合 setitem。
    """
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-patch-token")
    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-patch-token")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nexus.db")
    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    return TestClient(app)


HEADERS = {"Authorization": "Bearer test-patch-token"}


def test_patch_session_style_persists(client: TestClient) -> None:
    """合法 style 必须持久化并返回 200。"""
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")
    resp = client.patch(
        f"/api/sessions/{sid}",
        json={"style": "professional"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "style": "professional"}
    assert db.get_session(sid)["style"] == "professional"


def test_patch_session_style_invalid_returns_422(client: TestClient) -> None:
    """style 不合法(body Literal 校验失败)在 Pydantic parse 时被拒,返回 422。

    NOTE: 跟 plan 写的 400 + "invalid style" 不同 —— Literal[...] 是
    request body schema 级别的强约束,FastAPI 在 handler 跑之前就
    拒绝(422 Unprocessable Entity),handler 内 ValueError 路径只
    处理「literal 通过 + session 不存在 / db 异常」等运行时错。
    """
    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")
    resp = client.patch(
        f"/api/sessions/{sid}",
        json={"style": "bogus"},
        headers=HEADERS,
    )
    assert resp.status_code == 422


def test_patch_session_style_nonexistent_returns_400(client: TestClient) -> None:
    """literal 通过但 session 不存在 → db.update_session_style 抛 ValueError,
    handler 转 400 + detail(覆盖 plan 里的 "session 不存在" 路径)。"""
    resp = client.patch(
        "/api/sessions/nonexistent-sid",
        json={"style": "concise"},
        headers=HEADERS,
    )
    assert resp.status_code == 400
    assert "session 不存在" in resp.json()["detail"]


def test_patch_session_style_reloads_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATCH 应触发 reload_system_prompt 清 cache(为下次 get_agent 重建准备)。"""
    from nexus.backend.agent import _system_prompt

    # 触发一次 cache 填充
    _system_prompt.get_system_prompt(model_name="", style="default")
    assert len(_system_prompt._CACHED_PROMPT) >= 1

    sid = str(uuid.uuid4())
    db.create_session(sid, channel="test")
    resp = client.patch(
        f"/api/sessions/{sid}",
        json={"style": "concise"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    # PATCH 后 cache 应被清空
    assert _system_prompt._CACHED_PROMPT == {}
