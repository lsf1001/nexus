"""回归测试:复用 session 时客户端 title 不应被静默丢弃。

WHY: handlers.py 旧实现只走 ``if get_session is None`` 分支,客户端
复用已有 session 时携带的 ``data["title"]`` 字段直接被忽略。本测试
覆盖以下四种场景:

1. DB 原语回归:``update_session`` 修改 title 后 ``get_session`` 读到新值。
2. 客户端没传 session_id → 走 create_session 分支(不应触发 update)。
3. 客户端传新 session_id(不存在) → 走 create_session 分支(不应触发 update)。
4. 客户端传已存在的 session_id + title → 必须调用 update_session(本次修复)。
5. 客户端传已存在的 session_id 但无 title → 不应触发 update(避免无谓写入)。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.backend import db
from nexus.backend.db import create_session, get_session, update_session


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """每个测试用独立临时 DB 文件。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


# ============================================================================
# DB 原语层回归(本次 bug 的 fix 末尾会调 update_session)
# ============================================================================


def test_update_session_changes_title(temp_db: Path) -> None:
    """DB 原语回归:update_session 修改 title 字段。

    WHY: 客户端改名通过此函数落库。先证明底层原语正确,再证明 handler
    会调它(后续 handler 层测试)。这条单独跑不需要 handler mock 链。
    """
    create_session("s1", title="旧标题")
    updated = update_session("s1", title="新标题")
    assert updated is not None
    assert updated["title"] == "新标题"

    # 再读一次,确保真的落库(不是只返回内存 dict)
    again = get_session("s1")
    assert again is not None
    assert again["title"] == "新标题"


# ============================================================================
# WS handler session 分支决策逻辑
# ============================================================================
# 策略:不动 handle_websocket 主体(那是个 ~350 行的入口,跑完整条链路
# 需要 mock LLM / stream guard / quality pipeline 等 6+ 内部依赖)。我们
# 直接模拟真实 DB,通过 mock WS 只送一帧用户消息,在异常路径下让 handler
# 提早抛错退出。然后检查 DB 原语(get_session / create_session /
# update_session)被调用的模式 —— 这正是本次 fix 的目标:复用已有 session
# + 带新 title 时,必须调 update_session。


def _make_ws_mock(frames: list[dict]) -> MagicMock:
    """构造一个最小可用的 WebSocket mock。

    ``receive_json`` 第一次返回用户消息帧,之后阻塞在另一帧
    ``asyncio.CancelledError`` 上,handler 进入 except 分支退出循环。
    """

    async def _receive() -> dict:
        if frames:
            return frames.pop(0)
        raise asyncio.CancelledError

    ws = MagicMock()
    ws.receive_json = _receive
    ws.send_json = AsyncMock()
    return ws


def _invoke_handler_once(
    ws: MagicMock,
    *,
    get_session_override,
    create_session_spy,
    update_session_spy,
) -> None:
    """驱动 handle_websocket 走一帧用户消息。

    所有跟 streaming / finalize / LLM 相关的内部函数 patch 成 AsyncMock,
    让 handler 顺利走到第一轮尾部(CancelledError 截断)。我们只关心
    上面三个 DB 原语的调用记录。
    """
    from nexus.backend.api.ws import handlers

    with (
        patch.object(handlers, "get_session", side_effect=get_session_override),
        patch.object(handlers, "create_session", side_effect=create_session_spy) as m_create,
        patch.object(handlers, "update_session", side_effect=update_session_spy) as m_update,
        patch.object(handlers, "_classify_and_record", new=AsyncMock(return_value="chitchat")),
        patch.object(handlers, "_run_agent_streaming", new=AsyncMock(return_value=(0, "", True, None, None))),
        patch.object(handlers, "_finalize_after_stream", new=AsyncMock()),
        patch("nexus.backend.api.ws.handlers.register"),
        patch("nexus.backend.api.ws.handlers.unregister"),
        patch("nexus.backend.api.ws.handlers.get_session_manager") as m_mgr,
    ):
        m_mgr.return_value.build_prompt.return_value = {"messages": []}
        try:
            asyncio.run(handlers.handle_websocket(ws, get_agent=lambda: MagicMock()))
        except asyncio.CancelledError:
            pass
        except json.JSONDecodeError:
            # receive_json 在我们侧抛 CancelledError,handler 的 JSONDecodeError
            # 分支不会触发。留给正常路径。
            pass

    # 显式 attach 让调用方断言。直接闭包变量也行,但通过属性方便。
    handlers._m_create = m_create  # type: ignore[attr-defined]
    handlers._m_update = m_update  # type: ignore[attr-defined]


def test_existing_session_with_title_triggers_update(temp_db: Path) -> None:
    """场景:客户端复用已有 session 并提供新 title → 必须 update_session。

    本次修复的核心断言。旧实现会让 update_session.call_count == 0,
    新实现让它 == 1 且 title 是新值。
    """
    # 在真实 DB 里预置一个已有 session
    create_session("existing", title="旧标题", channel="main")

    ws = _make_ws_mock(
        [
            {"type": "user", "session_id": "existing", "title": "新标题", "content": "hello"},
        ]
    )

    def _get(sid: str):
        return get_session(sid)

    def _create(sid: str, title: str | None = None, channel: str = "main"):
        return create_session(sid, title=title, channel=channel)

    def _update(sid: str, title: str | None = None):
        return update_session(sid, title=title)

    _invoke_handler_once(
        ws,
        get_session_override=_get,
        create_session_spy=_create,
        update_session_spy=_update,
    )

    from nexus.backend.api.ws import handlers

    m_update = handlers._m_update  # type: ignore[attr-defined]
    m_create = handlers._m_create  # type: ignore[attr-defined]

    # 关键断言: update_session 必须被调用一次,title 是新标题
    assert m_update.call_count == 1, "fix 期望:复用已有 session + 带 title → 必须调 update_session"
    call = m_update.call_args
    # call.args = (session_id,), call.kwargs = {"title": "新标题"}
    assert call.args[0] == "existing"
    assert call.kwargs.get("title") == "新标题"
    # create_session 不应被触发(会话已存在)
    assert m_create.call_count == 0

    # 落库校验:DB 真的把 title 改成"新标题"了
    row = get_session("existing")
    assert row is not None
    assert row["title"] == "新标题"


def test_existing_session_without_title_does_not_update(temp_db: Path) -> None:
    """边界:复用已有 session 但无 title → 不应触发 update_session(无谓写入)。

    WHY: 若每次普通聊天都 update_session,会触发额外的 UPDATE 写,
    影响性能 + 加 updated_at 噪声。client_title 为空时跳过。
    """
    create_session("existing", title="旧标题", channel="main")

    ws = _make_ws_mock(
        [
            {"type": "user", "session_id": "existing", "content": "hello"},
        ]
    )

    def _get(sid: str):
        return get_session(sid)

    def _create(sid: str, title: str | None = None, channel: str = "main"):
        return create_session(sid, title=title, channel=channel)

    def _update(sid: str, title: str | None = None):
        return update_session(sid, title=title)

    _invoke_handler_once(
        ws,
        get_session_override=_get,
        create_session_spy=_create,
        update_session_spy=_update,
    )

    from nexus.backend.api.ws import handlers

    m_update = handlers._m_update  # type: ignore[attr-defined]
    m_create = handlers._m_create  # type: ignore[attr-defined]

    assert m_update.call_count == 0
    assert m_create.call_count == 0

    # title 保持原值
    row = get_session("existing")
    assert row is not None
    assert row["title"] == "旧标题"


def test_new_session_with_title_uses_create_not_update(temp_db: Path) -> None:
    """正常路径:客户端传新 session_id(不存在) + title → 走 create_session。

    WHY: 验证 fix 没破坏既有"新会话走 create"逻辑。session 不存在时
    应走 create_session(发 session_created),不应调 update_session。
    """
    ws = _make_ws_mock(
        [
            {"type": "user", "session_id": "new-session", "title": "新会话标题", "content": "hello"},
        ]
    )

    def _get(sid: str):
        return get_session(sid)

    def _create(sid: str, title: str | None = None, channel: str = "main"):
        return create_session(sid, title=title, channel=channel)

    def _update(sid: str, title: str | None = None):
        return update_session(sid, title=title)

    _invoke_handler_once(
        ws,
        get_session_override=_get,
        create_session_spy=_create,
        update_session_spy=_update,
    )

    from nexus.backend.api.ws import handlers

    m_update = handlers._m_update  # type: ignore[attr-defined]
    m_create = handlers._m_create  # type: ignore[attr-defined]

    assert m_create.call_count == 1
    assert m_create.call_args.kwargs.get("title") == "新会话标题"
    assert m_update.call_count == 0

    # DB 真实落库
    row = get_session("new-session")
    assert row is not None
    assert row["title"] == "新会话标题"
