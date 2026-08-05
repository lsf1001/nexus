"""会话导出 markdown endpoint 单测。

Round 3 Task 3.3:``GET /api/sessions/{sid}/export.md`` 把整个会话
序列化为纯 markdown(text/markdown; charset=utf-8),给用户提供「把对话
发到公众号 / GitHub / 邮件附件」的便携路径。覆盖三类:
- 正常:title + 多角色 messages 全部出现,thinking_content 不出现
- 边界:空消息会话仍可导出(只剩 header)
- 异常:不存在的 sid → 404
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend import config as config_module
from nexus.backend import db
from nexus.backend.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """隔离 DB + ws_token,跟 sessions.py router 的 require_token 对齐。

    sessions router 走 ``Depends(require_token)``,需 Authorization 头。
    复制 test_projects_api.py 同模式:setenv + setitem(CONFIG["ws_token"])
    双保险(CONFIG 在模块加载时绑定,setenv 仅影响后续读取)。
    """
    db_path = tmp_path / "test_export.db"
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-export-token")
    monkeypatch.setitem(config_module.CONFIG, "db_path", str(db_path))
    monkeypatch.setitem(config_module.CONFIG, "database_url", str(db_path))
    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-export-token")
    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    return TestClient(app)


HEADERS = {"Authorization": "Bearer test-export-token"}


def test_export_markdown_contains_title_and_messages(client: TestClient) -> None:
    """title + 两条 user/assistant 消息 + role header 全出现,thinking 不导出。"""
    sid = db.create_session(session_id="sess-export", title="BTC 行情讨论", channel="test")
    db.add_message("msg-u1", sid["id"], "user", "BTC 接下来怎么走")
    db.add_message(
        "msg-a1",
        sid["id"],
        "assistant",
        "看美联储利率决议",
        thinking_content="内部推理:还要看通胀",
    )

    response = client.get(f"/api/sessions/{sid['id']}/export.md", headers=HEADERS)

    assert response.status_code == 200
    body = response.text
    assert "# BTC 行情讨论" in body
    assert f"**Session ID**: `{sid['id']}`" in body
    assert "**Messages**: 2" in body
    # 两条消息按 created_at 升序排(同一时间戳下 INSERT 顺序也是稳定顺序)
    assert "## User" in body
    assert "## Assistant" in body
    assert "BTC 接下来怎么走" in body
    assert "看美联储利率决议" in body
    # thinking_content 不在普通 markdown 用户视图内
    assert "内部推理" not in body
    assert "还要看通胀" not in body


def test_export_markdown_404_on_missing_session(client: TestClient) -> None:
    """不存在的 sid → 404,detail 含「会话不存在」。"""
    response = client.get("/api/sessions/does-not-exist/export.md", headers=HEADERS)
    assert response.status_code == 404
    assert "会话不存在" in response.json()["detail"]


def test_export_markdown_media_type_is_text_markdown(client: TestClient) -> None:
    """Content-Type 必须是 text/markdown; charset=utf-8(浏览器 / curl
    看到这头会自动渲染或下载成 .md)。

    FastAPI ``Response(media_type=...)`` 会在 header 里拼 ``; charset=utf-8``,
    这里直接断言完整字符串(避免 .startswith / .contains 模糊匹配漏检)。
    """
    sid = db.create_session(session_id="sess-mt", title="媒体类型验证", channel="test")
    response = client.get(f"/api/sessions/{sid['id']}/export.md", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
