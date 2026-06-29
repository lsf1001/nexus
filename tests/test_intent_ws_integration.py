"""WS handler 辅助函数 _classify_and_record:分类 + 入库 intent 列。

2026-06-29 重构后 _classify_and_record 不再调 LLM(intent 改用纯函数
:classify_intent` 正则推断),测试改为验证:

  - 输入匹配知识类 pattern → 入库 intent=knowledge
  - 输入匹配任务类 pattern → 入库 intent=task
  - WS 心跳帧照样发出(event_id=last_event_id+1,content=正在识别...)
"""

from __future__ import annotations

import sqlite3

import pytest

from nexus.backend import db
from nexus.backend.intent.router import (
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
)


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


class _RecordingWS:
    """最小 fake WebSocket:记录所有 send_json 调用,便于断言心跳帧。"""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, data) -> None:
        self.frames.append(data)


async def test_classify_and_record_knowledge_persists_intent(temp_db) -> None:
    """知识类问句 → INTENT_KNOWLEDGE 入库 + 心跳帧发出。"""
    from nexus.backend.api.ws import _classify_and_record

    sid = "s-knowledge"
    db.create_session(sid, title="t", channel="main")

    ws = _RecordingWS()
    intent = await _classify_and_record(
        ws,
        session_id=sid,
        user_content="元力股份 能买吗",
        last_event_id=42,
    )
    assert intent == INTENT_KNOWLEDGE

    # 入库校验
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_KNOWLEDGE

    # 心跳帧校验:event_id = last_event_id + 1,content 是中文
    assert len(ws.frames) == 1
    frame = ws.frames[0]
    assert frame["type"] == "thinking"
    assert frame["event_id"] == 43
    assert "识别" in frame["content"]


async def test_classify_and_record_task_persists_intent(temp_db) -> None:
    """任务类指令 → INTENT_TASK 入库。"""
    from nexus.backend.api.ws import _classify_and_record

    sid = "s-task"
    db.create_session(sid, title="t", channel="main")

    ws = _RecordingWS()
    intent = await _classify_and_record(
        ws,
        session_id=sid,
        user_content="帮我写一个 Python 函数",
    )
    assert intent == INTENT_TASK

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_TASK


async def test_classify_and_record_chitchat_falls_back(temp_db) -> None:
    """闲聊 / 无 pattern 命中 → INTENT_CHITCHAT 兜底。"""
    from nexus.backend.api.ws import _classify_and_record

    sid = "s-chitchat"
    db.create_session(sid, title="t", channel="main")

    ws = _RecordingWS()
    intent = await _classify_and_record(
        ws,
        session_id=sid,
        user_content="你好",
    )
    assert intent == INTENT_CHITCHAT

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_CHITCHAT


async def test_classify_and_record_heartbeat_uses_last_event_id_plus_one(temp_db) -> None:
    """心跳帧 event_id 必须 = last_event_id + 1(让客户端用 event_id 续流时心跳也合法)。

    WHY:心跳跟流内 event_id 单调衔接是 _classify_and_record 的契约(E2E
    2026-06-28 验证过客户端按 event_id 续点会跳过中间帧)。default 0 也对。
    """
    from nexus.backend.api.ws import _classify_and_record

    sid = "s-heartbeat"
    db.create_session(sid, title="t", channel="main")

    ws = _RecordingWS()
    await _classify_and_record(ws, session_id=sid, user_content="x", last_event_id=99)
    assert ws.frames[0]["event_id"] == 100

    sid2 = "s-heartbeat-2"
    db.create_session(sid2, title="t", channel="main")
    ws2 = _RecordingWS()
    await _classify_and_record(ws2, session_id=sid2, user_content="x", last_event_id=0)
    assert ws2.frames[0]["event_id"] == 1
