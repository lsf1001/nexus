"""share token CRUD 单测。

Round 3 Task 3.3:分享链接 7 天有效、可撤销。覆盖:
- create → DB 行存在 + expires_at = now + 7d
- get(token) → 拿回与 export.md 同格式 markdown
- revoke → 后续 get 返回 410 Gone
- 过期 token(模拟 expires_at 已过)→ get 返回 410 Gone

WHY 三类分离:这是用户对外公开链接的入口,一旦漏洞(过期仍可读 / 撤
销仍可读)后果严重 — 必须每条路径独立断言,不靠「拿得到就算成功」
的乐观语义。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.backend import config as config_module
from nexus.backend import db
from nexus.backend.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """隔离 DB + ws_token,与 test_session_export 同模式。"""
    db_path = tmp_path / "test_share_flow.db"
    monkeypatch.setenv("NEXUS_WS_TOKEN", "test-share-token")
    monkeypatch.setitem(config_module.CONFIG, "db_path", str(db_path))
    monkeypatch.setitem(config_module.CONFIG, "database_url", str(db_path))
    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-share-token")
    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    return TestClient(app)


HEADERS = {"Authorization": "Bearer test-share-token"}


def _create_session_with_messages(title: str = "分享测试会话") -> str:
    """helper:建会话 + 塞两条消息,返回 sid。"""
    sid = db.create_session(session_id=f"sess-share-{title}", title=title, channel="test")
    db.add_message("msg-share-u", sid["id"], "user", "用户问句")
    db.add_message("msg-share-a", sid["id"], "assistant", "助手回答")
    return sid["id"]


# ============================================================================
# DB helper 层(create_share_token / get_share_token / revoke_share_token)
# ============================================================================


def test_create_share_token_writes_row_and_7d_expiry(tmp_path: Path) -> None:
    """create_share_token → DB 行存在,expires_at 距 now ≈ 7 天 ± 60s。

    WHY ± 60s 容差:测试运行慢机器上 datetime.now() 取值可能在分钟边
    界两侧漂移;只要落在 6d23h ~ 7d1h 区间内就算通过(共享语义即可)。

    WHY 全部 naive datetime:db 层用 ``datetime.now()`` 无时区,与 UTC
    aware 类型混算会抛 TypeError;统一 naive 保持比较可行。
    """
    db.init_db()
    sid = _create_session_with_messages()
    before = datetime.now()

    result = db.create_share_token(sid, ttl_days=7)

    assert "token" in result and len(result["token"]) >= 32  # secrets.token_urlsafe(32) ≥ 43 字符
    assert "expires_at" in result

    # DB 验证
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT session_id, revoked_at, created_at, expires_at FROM share_tokens WHERE token = ?",
            (result["token"],),
        ).fetchone()
    assert row is not None
    assert row["session_id"] == sid
    assert row["revoked_at"] is None

    # expires_at - now ≈ 7 天
    expires = datetime.fromisoformat(row["expires_at"])
    delta = expires - before
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


def test_get_share_token_returns_active_row() -> None:
    """get_share_token 拿有效 token → 返回 dict 含 session_id + expires_at。"""
    db.init_db()
    sid = _create_session_with_messages()
    result = db.create_share_token(sid, ttl_days=7)

    fetched = db.get_share_token(result["token"])

    assert fetched is not None
    assert fetched["session_id"] == sid
    assert fetched["token"] == result["token"]
    assert fetched["revoked_at"] is None


def test_get_share_token_returns_none_when_revoked() -> None:
    """revoke_share_token 后,get_share_token → None(已判 revoked_at)。"""
    db.init_db()
    sid = _create_session_with_messages()
    result = db.create_share_token(sid, ttl_days=7)
    assert db.revoke_share_token(result["token"]) is True

    assert db.get_share_token(result["token"]) is None


def test_get_share_token_returns_none_when_expired() -> None:
    """token 过期(模拟时钟快进)→ get_share_token → None。

    WHY 单测覆盖:产品语义上「7 天过期」必须强制执行,不能因为 DB
    expires_at 写错字段 / 比较错方向而漏检。
    """
    db.init_db()
    sid = _create_session_with_messages()
    result = db.create_share_token(sid, ttl_days=7)
    # 直接 UPDATE 把 expires_at 改到过去
    with db.get_db() as conn:
        conn.execute(
            "UPDATE share_tokens SET expires_at = ? WHERE token = ?",
            ((datetime.now() - timedelta(days=1)).isoformat(), result["token"]),
        )

    assert db.get_share_token(result["token"]) is None


# ============================================================================
# HTTP endpoint 层(/api/sessions/{sid}/share + /api/share/{token})
# ============================================================================


def test_post_share_creates_token_returns_url_and_expiry(client: TestClient) -> None:
    """POST /share → 200 + {token, url, expires_at},token 在 DB 里。"""
    sid = _create_session_with_messages()
    response = client.post(f"/api/sessions/{sid}/share", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert body["url"].endswith(body["token"])
    assert body["url"].startswith("/api/share/")
    assert "expires_at" in body

    # DB 验证
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT session_id, revoked_at FROM share_tokens WHERE token = ?",
            (body["token"],),
        ).fetchone()
    assert row is not None and row["session_id"] == sid


def test_get_share_returns_markdown_with_messages(client: TestClient) -> None:
    """GET /api/share/{token} → 200 + markdown 与 export.md 同格式。"""
    sid = _create_session_with_messages(title="分享回看测试")
    post_resp = client.post(f"/api/sessions/{sid}/share", headers=HEADERS)
    token = post_resp.json()["token"]

    get_resp = client.get(f"/api/share/{token}", headers=HEADERS)

    assert get_resp.status_code == 200
    body = get_resp.text
    assert "# 分享回看测试" in body
    assert "**Messages**: 2" in body
    assert "## User" in body
    assert "## Assistant" in body
    assert "用户问句" in body
    assert "助手回答" in body


def test_get_share_returns_410_when_revoked(client: TestClient) -> None:
    """DELETE /api/share/{token} 后,GET 同 token → 410 Gone。"""
    sid = _create_session_with_messages()
    post_resp = client.post(f"/api/sessions/{sid}/share", headers=HEADERS)
    token = post_resp.json()["token"]

    del_resp = client.delete(f"/api/share/{token}", headers=HEADERS)
    assert del_resp.status_code == 410

    get_resp = client.get(f"/api/share/{token}", headers=HEADERS)
    assert get_resp.status_code == 410
    assert "已撤销" in get_resp.json()["detail"] or "已过期" in get_resp.json()["detail"]


def test_get_share_returns_410_when_expired(client: TestClient) -> None:
    """token 过期 → GET /api/share/{token} 返回 410 Gone。"""
    sid = _create_session_with_messages()
    post_resp = client.post(f"/api/sessions/{sid}/share", headers=HEADERS)
    token = post_resp.json()["token"]

    # 模拟过期:UPDATE expires_at 到过去
    with db.get_db() as conn:
        conn.execute(
            "UPDATE share_tokens SET expires_at = ? WHERE token = ?",
            ((datetime.now() - timedelta(hours=1)).isoformat(), token),
        )

    get_resp = client.get(f"/api/share/{token}", headers=HEADERS)
    assert get_resp.status_code == 410
