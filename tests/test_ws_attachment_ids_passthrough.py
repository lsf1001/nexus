"""回归测试:WS handler 必须把消息帧里的 ``attachment_ids`` 透传给 build_prompt。

WHY(2026-07-30 T11 发现的真实 gap):
Round 2 的附件链路是 前端 useChatSend 在 ``idsArr`` 非空时给 WSMessage 挂
``attachment_ids`` → WS handler 收帧 → ``sessions.build_prompt(session_id,
content, attachment_ids)`` 拉附件元数据拼 multi-part 让 LLM 真的看到附件。

但 ``handlers.py`` 这一环一直是裸调 ``build_prompt(session_id, user_content)``
—— 前端发了 ``attachment_ids`` 等于被静默丢弃,用户传的文件/图片 LLM 完全看
不见。本测试锁住透传行为,覆盖三类路径:

1. 正常:帧带 ``attachment_ids`` → build_prompt 第三个参数收到同样的 id 列表。
2. 边界:帧不带该字段 → 收到 ``None``(走原纯 text 路径,零回归)。
3. 边界/异常:``attachment_ids=[]`` 或非列表类型 → 同样收到 ``None``
   (空 list 透传下去会让 build_prompt 拿空 placeholders 做无谓查询)。

测试策略与 ``test_ws_session_title_update.py`` 一致:不动 ``handle_websocket``
主体(~350 行入口,跑完整链路要 mock LLM / stream guard / quality 等 6+ 依赖),
而是用最小 WS mock 只送一帧用户消息,patch 掉 streaming / finalize / 落库等
副作用,只断言 ``build_prompt`` 的调用参数。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.backend import db


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """独立临时 DB + 一条 default project 行。

    WHY 要塞 project 行:``sessions.project_id`` 有 ``REFERENCES projects(id)``
    外键,而 ``create_session`` 未传 project_id 时回落到 ``"default"``。DB 里
    没有 default project 行时 handler 建会话会撞 FOREIGN KEY constraint failed。
    直接 INSERT 而不调 ``ensure_default_project()``:后者会拷 AGENTS.md /
    link skills / 写 mcp.json,本测试不需要这些文件系统副作用
    (同 ``test_attachments_routes.py`` 的 fixture 做法)。
    """
    from datetime import UTC, datetime

    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    db.init_db()
    now = datetime.now(UTC).isoformat()
    with db.get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, display_name, path, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("default", "default", "默认项目", str(tmp_path / "default"), "", now, now),
        )
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


def _make_ws_mock(frames: list[dict]) -> MagicMock:
    """最小可用 WebSocket mock:送完 frames 后抛 CancelledError 让 handler 退出。"""

    async def _receive() -> dict:
        if frames:
            return frames.pop(0)
        raise asyncio.CancelledError

    ws = MagicMock()
    ws.receive_json = _receive
    ws.send_json = AsyncMock()
    return ws


def _capture_build_prompt_call(frame: dict) -> Any:
    """驱动 handle_websocket 走一帧用户消息,返回 build_prompt 的 mock。

    调用方从返回值的 ``call_args`` 读取实参,断言 attachment_ids 透传是否正确。
    """
    from nexus.backend.api.ws import handlers

    with (
        patch.object(handlers, "_classify_and_record", new=AsyncMock(return_value="chitchat")),
        patch.object(
            handlers,
            "_run_agent_streaming",
            new=AsyncMock(return_value=(0, "", True, None, None)),
        ),
        patch.object(handlers, "_finalize_after_stream", new=AsyncMock()),
        patch("nexus.backend.api.ws.handlers.register"),
        patch("nexus.backend.api.ws.handlers.unregister"),
        patch("nexus.backend.api.ws.handlers.get_session_manager") as m_mgr,
    ):
        m_mgr.return_value.build_prompt.return_value = {"messages": []}
        try:
            asyncio.run(handlers.handle_websocket(_make_ws_mock([frame]), get_agent=lambda: MagicMock()))
        except asyncio.CancelledError:
            pass
        return m_mgr.return_value.build_prompt


def test_attachment_ids_passed_through(temp_db: Path) -> None:
    """正常路径:帧带 attachment_ids → build_prompt 收到同样的列表。

    这是本次 fix 的核心断言。旧实现下第三个参数根本不存在(裸调两参)。
    """
    build_prompt = _capture_build_prompt_call(
        {"type": "user", "content": "解释这两个文件", "attachment_ids": ["a1", "a2"]}
    )

    assert build_prompt.call_count == 1
    call = build_prompt.call_args
    # 位置参数: (session_id, user_content, attachment_ids)
    assert call.args[1] == "解释这两个文件"
    assert call.args[2] == ["a1", "a2"], "fix 期望:帧里的 attachment_ids 必须透传给 build_prompt"


def test_missing_attachment_ids_passes_none(temp_db: Path) -> None:
    """边界:帧不带 attachment_ids → 收到 None,走原纯 text 路径(零回归)。"""
    build_prompt = _capture_build_prompt_call({"type": "user", "content": "只是普通聊天"})

    assert build_prompt.call_count == 1
    assert build_prompt.call_args.args[2] is None


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param([], id="empty-list"),
        pytest.param("a1", id="string-not-list"),
        pytest.param(None, id="explicit-null"),
    ],
)
def test_falsy_or_invalid_attachment_ids_normalize_to_none(temp_db: Path, raw: Any) -> None:
    """边界/异常:空列表、非列表类型、显式 null 都规约成 None。

    WHY:空 list 若透传下去,build_prompt 会拿空 placeholders 去查 attachments
    表(拉不到元数据),多一次无谓查询;非列表类型(客户端 bug / 老版本)直接
    透传会让 build_prompt 内的 ``",".join("?" * len(...))`` 行为失真。
    """
    build_prompt = _capture_build_prompt_call({"type": "user", "content": "hello", "attachment_ids": raw})

    assert build_prompt.call_count == 1
    assert build_prompt.call_args.args[2] is None


def test_non_string_attachment_ids_coerced_to_str(temp_db: Path) -> None:
    """边界:客户端误传数字 id → 强制转 str(build_prompt 的 SQL 参数按 str 绑定)。"""
    build_prompt = _capture_build_prompt_call({"type": "user", "content": "hello", "attachment_ids": [1, 2]})

    assert build_prompt.call_args.args[2] == ["1", "2"]
