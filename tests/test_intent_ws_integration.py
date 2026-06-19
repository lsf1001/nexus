"""WS handler 辅助函数 _classify_and_record:分类 + 入库 intent 列。"""

from __future__ import annotations

import sqlite3

import pytest

from nexus.backend import db
from nexus.backend.intent.router import (
    INTENT_CHITCHAT,
    INTENT_TASK,
)


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


async def test_classify_and_record_persists_intent(temp_db):
    """get_intent_llm 返回 None 时,fallback chitchat 并入库。"""
    from nexus.backend.api.ws import _classify_and_record

    sid = "s-test"
    db.create_session(sid, title="t", channel="main")

    intent = await _classify_and_record(
        get_intent_llm=lambda: None,
        session_id=sid,
        user_content="你好",
    )
    assert intent == INTENT_CHITCHAT

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_CHITCHAT


async def test_classify_and_record_uses_llm_intent(temp_db, monkeypatch):
    """get_intent_llm 返回 fake LLM,分类结果应写入。"""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage

    from nexus.backend.api.ws import _classify_and_record

    class _TaskLLM(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise NotImplementedError

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, input, config=None, stop=None, **kwargs):
            return AIMessage(
                content="",
                tool_calls=[{"name": "route_task_execute", "args": {"text": "x"}, "id": "c1"}],
            )

    sid = "s2"
    db.create_session(sid, title="t", channel="main")

    intent = await _classify_and_record(
        get_intent_llm=lambda: _TaskLLM(),
        session_id=sid,
        user_content="帮我写代码",
    )
    assert intent == INTENT_TASK

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_TASK
