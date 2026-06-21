"""回归测试：本轮修复的 bug（review top 10）。

1. delete_model 在无 fallback 时不返回 success，必须抛 400
2. find_latest_session_by_user 正确按 user_id 模式 + channel 匹配
3. _resolve_wechat_session 走完 lock-in-lock 路径
4. setup: ensure find_latest returns None for unknown user
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

# 强制使用临时 DB，避免污染 ~/.nexus
os.environ.setdefault("NEXUS_HOME", tempfile.mkdtemp(prefix="nexus-test-"))

from fastapi.testclient import TestClient

from nexus.backend.db import (
    add_message,
    create_session,
    find_latest_session_by_user,
    init_db,
    get_session,
)
from nexus.backend.main import _resolve_wechat_session, _wechat_sessions_lock
from nexus.backend.routes.model_config import init_router


def _client_with_models(models: list[dict]) -> TestClient:
    """构造一个临时 client，注入指定 models.json 内容。"""
    from nexus.backend.main import app
    from nexus.backend.config import CONFIG
    from nexus.backend.models_config import save_models

    init_db()
    save_models({"models": models})

    # 设 token 让 require_token 通过
    CONFIG["ws_token"] = "test-token"

    # 注入 router 依赖（生产由 main.lifespan 注入；测试需手动）
    def _no_create(_model, _mcp):
        return object()  # 非 None 占位

    def _set_global(_agent):
        return None

    init_router(
        agent_lock=__import__("threading").RLock(),
        mcp_tools=[],
        create_agent_with_model=_no_create,
        set_global_agent=_set_global,
    )
    headers = {"Authorization": "Bearer test-token"}
    return TestClient(app, headers=headers)


def test_delete_active_model_without_fallback_returns_400():
    """修复 #2: 只有 active 一个有 key 的 model,再删它,必须 400 不能 None agent。"""
    client = _client_with_models(
        [
            {"id": "a", "name": "A", "api_key": "sk-aaa", "is_active": True},
        ]
    )
    # 删 a 应该返回 400,因为删完就一个不剩
    r = client.delete("/api/models/a")
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    assert "没有其它" in r.text or "至少" in r.text


def test_delete_active_with_valid_fallback_succeeds():
    """有 fallback 时,删 active 应该 200,fallback 升为 active。"""
    client = _client_with_models(
        [
            {"id": "a", "name": "A", "api_key": "sk-aaa", "is_active": True},
            {"id": "b", "name": "B", "api_key": "sk-bbb", "is_active": False},
        ]
    )
    r = client.delete("/api/models/a")
    assert r.status_code == 200, r.text
    # 验证 a 已删,b 还在
    r2 = client.get("/api/models")
    assert r2.status_code == 200
    models = r2.json()
    ids = {m["id"] for m in models}
    assert "a" not in ids
    assert "b" in ids


def test_find_latest_session_by_user():
    """修复 #5: find_latest_session_by_user 按 user_id 子串 + channel 匹配。"""
    init_db()
    sid1 = str(uuid.uuid4())
    sid2 = str(uuid.uuid4())
    create_session(sid1, title="微信 bob", channel="wechat")
    create_session(sid2, title="微信 alice", channel="wechat")
    add_message("m1", sid1, "user", "user_bob@x: 第一条")
    add_message("m2", sid1, "user", "user_bob@x: 第二条")
    add_message("m3", sid2, "user", "user_alice@x: 第一条")

    assert find_latest_session_by_user("bob", "wechat") == sid1
    assert find_latest_session_by_user("alice", "wechat") == sid2
    assert find_latest_session_by_user("unknown", "wechat") is None


def test_resolve_wechat_session_creates_and_reuses():
    """修复 #5: 同一 user_id 两次走 _resolve_wechat_session 拿到同一个 session。"""
    init_db()
    # 第一次 → 新建
    sid_a = __import__("asyncio").run(
        _resolve_wechat_session("user_xyz", "acc1")
    )
    # 第二次 → 复用
    sid_b = __import__("asyncio").run(
        _resolve_wechat_session("user_xyz", "acc1")
    )
    assert sid_a == sid_b
    assert get_session(sid_a) is not None
