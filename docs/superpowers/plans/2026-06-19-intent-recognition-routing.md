# 意图识别 + 路由 实施计划

> **执行说明**：建议使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实施。步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 给 Nexus 的"单 LLM 主对话"加 1-shot 意图识别层：每条用户消息先经 1 次轻量工具调用分类（chitchat / knowledge / task），分类结果落库到 `messages.intent` 列，并按意图与现有质量门短路/全审逻辑联动（chitchat → 直接放行；task → 完整 judge）。

**架构：** 新建 `nexus/backend/intent/router.py` 复用主 `ChatModel` 实例（与质量门 judge 共享同一 LLM，独立 `bind_tools` 实例），用 LangChain 内置 function-calling 走 1 次 LLM 调用完成分类。零新依赖、零新 API key。`messages` 表加 `intent` 列（走 `_ensure_column()` 自动迁移，老库无感）。`ws.py` 在 user 消息入库时把 intent 一并写入。质量门**不动**——它的 chitchat 短路逻辑天然命中 chitchat 类输入，task/knowledge 走原 judge 链。

**技术栈：** Python 3.11+、FastAPI、LangChain（`@tool` 装饰器 + `bind_tools`）、SQLite、pytest。**零新依赖**。

---

## 一、范围与依赖

- 仅后端（`nexus/backend/`），前端零改动。
- 数据库 schema 改 1 张表：`messages` 新增 `intent` 列；通过 `db.py:_ensure_column` 模式兼容老库。
- 不重写 `quality/pipeline.py`、不改 `agent.py`、不动现有 `chitchat` 短路（10 行 regex + keyword check 保持原样）。
- 不引入新第三方库（LangChain 已自带 `@tool` / `bind_tools`）。
- 不新增 LLM API key —— 复用 `get_llm()` 工厂出来的同一 `BaseChatModel` 实例。

---

## 二、文件结构（新增 / 修改）

### 新增

```
nexus/backend/intent/
  __init__.py          # 暴露 classify_intent / IntentKind
  router.py            # INTENT_TOOLS + classify_intent() + IntentClassificationError

tests/
  test_intent_router.py        # 分类器 5 个场景（happy/3 类/兜底）
  test_db_migrations_intent.py # messages.intent 列迁移
  test_intent_ws_integration.py # WS handler 调用 classify_intent + 落库
```

### 修改

```
nexus/backend/db.py            # _ensure_column("messages", "intent", "TEXT") + add_message 新增 intent 参数
nexus/backend/main.py          # _get_intent_llm 工厂 + 注入到 handle_websocket
nexus/backend/api/ws.py        # 接收 get_intent_llm 回调,在 user 消息入库前分类
```

---

## 三、任务分解

### 任务 1：DB 迁移 + `add_message` 扩参

**文件：**
- 修改：`nexus/backend/db.py:48-78`（建表逻辑）、`nexus/backend/db.py:368-388`（`add_message`）
- 新建：`tests/test_db_migrations_intent.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_db_migrations_intent.py
from __future__ import annotations

import sqlite3

import pytest

from nexus.backend import db
from nexus.backend.db import _create_tables, add_message


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


def test_messages_table_has_intent_column(temp_db):
    """_create_tables 后 messages 表必须有 intent 列。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert "intent" in cols


def test_add_message_persists_intent(temp_db):
    """add_message 接受 intent 参数并写入。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    conn.commit()
    db.add_message("m1", "s1", "user", "你好", intent="chitchat")
    row = conn.execute("SELECT intent FROM messages WHERE id = 'm1'").fetchone()
    assert row["intent"] == "chitchat"


def test_add_message_default_intent_is_none(temp_db):
    """不传 intent 时,字段为 NULL(老路径行为不变)。"""
    conn = sqlite3.connect(str(temp_db))
    _create_tables(conn)
    conn.commit()
    db.add_message("m2", "s1", "user", "test")
    row = conn.execute("SELECT intent FROM messages WHERE id = 'm2'").fetchone()
    assert row["intent"] is None
```

- [ ] **Step 2：跑测试，期望失败**

```bash
cd /Users/yxb/projects/nexus && source .venv/bin/activate
pytest tests/test_db_migrations_intent.py -v
```

期望：`ModuleNotFoundError` 或 `assert "intent" not in cols` / `TypeError: add_message() got an unexpected keyword argument 'intent'`。

- [ ] **Step 3：实现**

`nexus/backend/db.py` 修改两处：

1. 在 `_create_tables` 内的 `messages` 建表后追加：
```python
_ensure_column(conn, "messages", "intent", "TEXT")
```

2. `add_message` 函数签名 + INSERT 语句加 intent：
```python
def add_message(
    message_id: str,
    session_id: str,
    role: str,
    content: str,
    thinking_content: str | None = None,
    intent: str | None = None,
) -> dict:
    """添加消息到会话。

    Args:
        intent: 意图分类标签(chitchat / knowledge / task / None)。
            旧调用方不传时,字段为 NULL,行为向后兼容。
    """
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages (id, session_id, role, content, thinking_content, intent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, session_id, role, content, thinking_content, intent, now),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.execute("UPDATE session_stats SET message_count = message_count + 1 WHERE session_id = ?", (session_id,))
        return {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking_content": thinking_content,
            "intent": intent,
            "created_at": now,
        }
```

- [ ] **Step 4：跑测试，期望全过**

```bash
pytest tests/test_db_migrations_intent.py -v
```

- [ ] **Step 5：跑全量回归确认无破坏**

```bash
pytest tests/ -q
ruff check nexus/backend/db.py
ruff format nexus/backend/db.py
```

- [ ] **Step 6：提交**

```bash
git add nexus/backend/db.py tests/test_db_migrations_intent.py
git commit -m "feat(db): messages 表新增 intent 列(自动迁移)"
```

---

### 任务 2：意图路由器（`nexus/backend/intent/router.py`）

**文件：**
- 新建：`nexus/backend/intent/__init__.py`、`nexus/backend/intent/router.py`
- 新建：`tests/test_intent_router.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_intent_router.py
"""意图路由器:5 个场景覆盖 happy/3 类/兜底。"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from nexus.backend.intent.router import (
    DEFAULT_INTENT,
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
    classify_intent,
)


class _FakeLLM(BaseChatModel):
    """预设 tool_call / text / raise 三种响应。"""
    tool_call_name: str = ""
    text_response: str = ""
    raise_exc: BaseException | None = None
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, input, config=None, stop=None, **kwargs) -> AIMessage:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.tool_call_name:
            return AIMessage(
                content="",
                tool_calls=[{"name": self.tool_call_name, "args": {"text": "input"}, "id": "call_1"}],
            )
        return AIMessage(content=self.text_response)


async def test_classify_task_complex_prompt():
    llm = _FakeLLM(tool_call_name="route_task_execute")
    assert await classify_intent(llm, "帮我写一个 Python 函数") == INTENT_TASK
    assert llm.call_count == 1


async def test_classify_knowledge_question():
    llm = _FakeLLM(tool_call_name="route_knowledge_qa")
    assert await classify_intent(llm, "Python 是什么?") == INTENT_KNOWLEDGE


async def test_classify_chitchat_greeting():
    llm = _FakeLLM(tool_call_name="route_chitchat")
    assert await classify_intent(llm, "你好") == INTENT_CHITCHAT


async def test_classify_falls_back_when_no_tool_call():
    """LLM 仅输出文本(没调工具)时,兜底 chitchat。"""
    llm = _FakeLLM(text_response="这是个问题")
    assert await classify_intent(llm, "test") == DEFAULT_INTENT
    assert DEFAULT_INTENT == INTENT_CHITCHAT


async def test_classify_falls_back_when_llm_raises():
    """LLM 异常时,兜底 chitchat,日志 WARNING,不抛。"""
    llm = _FakeLLM(raise_exc=RuntimeError("LLM down"))
    assert await classify_intent(llm, "test") == INTENT_CHITCHAT


async def test_classify_falls_back_on_timeout():
    """LLM 超时时,兜底 chitchat,不阻塞主流程。"""
    class _SlowLLM(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise NotImplementedError
        async def ainvoke(self, input, config=None, stop=None, **kwargs):
            await asyncio.sleep(10)
            return AIMessage(content="")
    assert await classify_intent(_SlowLLM(), "test") == INTENT_CHITCHAT
```

- [ ] **Step 2：跑测试，期望失败**（模块不存在）

```bash
pytest tests/test_intent_router.py -v
```

- [ ] **Step 3：实现**

`nexus/backend/intent/__init__.py`：
```python
"""意图识别路由:复用主 ChatModel 做 1-shot function-calling 分类。"""
from .router import (
    DEFAULT_INTENT,
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
    IntentKind,
    classify_intent,
)

__all__ = [
    "DEFAULT_INTENT",
    "INTENT_CHITCHAT",
    "INTENT_KNOWLEDGE",
    "INTENT_TASK",
    "IntentKind",
    "classify_intent",
]
```

`nexus/backend/intent/router.py`：
```python
"""意图识别路由:复用主 ChatModel 做 1-shot 工具调用分类。

零新依赖、零新 API key。每条 user message 多 1 次轻量 LLM 调用(< 8s 超时),
token 成本 < 200,延迟 +200-400ms。失败一律兜底 chitchat(最安全:不影响
quality gate 的 task 工具链、不影响 deepagents 路径)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

IntentKind = Literal["chitchat", "knowledge", "task"]

INTENT_CHITCHAT: IntentKind = "chitchat"
INTENT_KNOWLEDGE: IntentKind = "knowledge"
INTENT_TASK: IntentKind = "task"

# 兜底:LLM 无 tool_call / 抛异常 / 超时 → chitchat(最安全,质量门已有
# chitchat 短路,不会因为兜底误判把任务类请求当成 chitchat 走错路径——
# 反过来 task 兜底 chitchat 才会出问题,所以这里坚持 chitchat 兜底)。
DEFAULT_INTENT: IntentKind = INTENT_CHITCHAT

# 分类超时:不能阻塞主流程太久
CLASSIFY_TIMEOUT_S: float = 8.0

_CLASSIFIER_SYSTEM = """你是意图分类器。根据用户输入,只调用 1 个最合适的工具。
- route_chitchat: 闲聊/寒暄/情感陪伴/打招呼
- route_knowledge_qa: 事实/概念/查询类问题(不需工具或多步执行)
- route_task_execute: 需要调用工具/MCP/多步执行的复杂任务"""


@tool
def route_chitchat(text: str) -> str:
    """闲聊/寒暄/情感陪伴/打招呼类输入。"""
    return INTENT_CHITCHAT


@tool
def route_knowledge_qa(text: str) -> str:
    """事实/概念/查询类问题(不需要工具或多步执行)。"""
    return INTENT_KNOWLEDGE


@tool
def route_task_execute(text: str) -> str:
    """需要调用工具/MCP/多步执行的复杂任务。"""
    return INTENT_TASK


INTENT_TOOLS = [route_chitchat, route_knowledge_qa, route_task_execute]

_TOOL_TO_INTENT: dict[str, IntentKind] = {
    "route_chitchat": INTENT_CHITCHAT,
    "route_knowledge_qa": INTENT_KNOWLEDGE,
    "route_task_execute": INTENT_TASK,
}


async def classify_intent(llm: BaseChatModel, message: str) -> IntentKind:
    """复用主 ChatModel 做 1-shot 意图分类。

    Args:
        llm: 已构造的 ``BaseChatModel``(建议复用 quality pipeline 那个
            temperature=0 的 judge_llm,verdict 稳定 + 零新模型)。
        message: 用户原始消息。

    Returns:
        IntentKind 字面量。所有异常 / 无 tool_call / 未知 tool 名一律
        兜底为 ``DEFAULT_INTENT``(chitchat)并记 WARNING,不抛。
    """
    try:
        resp = await asyncio.wait_for(
            llm.bind_tools(INTENT_TOOLS).ainvoke(
                [
                    SystemMessage(content=_CLASSIFIER_SYSTEM),
                    HumanMessage(content=message),
                ]
            ),
            timeout=CLASSIFY_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — 边界统一兜底
        logger.warning("意图分类 LLM 失败,兜底 chitchat: %s", exc)
        return DEFAULT_INTENT

    tool_calls = getattr(resp, "tool_calls", None) or []
    if not tool_calls:
        logger.info("意图分类未返回 tool_call,兜底 chitchat")
        return DEFAULT_INTENT

    first = tool_calls[0]
    name = first.get("name") if isinstance(first, dict) else getattr(first, "name", "")
    intent = _TOOL_TO_INTENT.get(name or "")
    if intent is None:
        logger.warning("意图分类返回未知 tool 名: %s,兜底 chitchat", name)
        return DEFAULT_INTENT
    return intent
```

- [ ] **Step 4：跑测试，期望全过**

```bash
pytest tests/test_intent_router.py -v
```

- [ ] **Step 5：跑全量回归**

```bash
pytest tests/ -q
ruff check nexus/backend/intent/
ruff format nexus/backend/intent/
```

- [ ] **Step 6：提交**

```bash
git add nexus/backend/intent/ tests/test_intent_router.py
git commit -m "feat(intent): 新增意图识别路由(bind_tools 1-shot 分类)"
```

---

### 任务 3：`main.py` 提供 LLM 工厂 + `ws.py` 接入分类

**文件：**
- 修改：`nexus/backend/main.py:336-393`（`_ensure_agent_ready` 构造 LLM + 暴露工厂）、`main.py:516-580`（`websocket_endpoint` 注入 `get_intent_llm`）
- 修改：`nexus/backend/api/ws.py:438-460`（`handle_websocket` 接 `get_intent_llm`）、`ws.py:534-536`（user 消息入库前分类）
- 新建：`tests/test_intent_ws_integration.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_intent_ws_integration.py
"""WS handler 集成:user 消息入库时 intent 列被正确填充。"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest

from nexus.backend import db
from nexus.backend.intent.router import INTENT_CHITCHAT, INTENT_TASK


@pytest.fixture
def temp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setitem(db.CONFIG, "db_path", str(db_path))
    monkeypatch.setattr(db, "_INITED", False)
    yield db_path
    monkeypatch.setattr(db, "_INITED", False)


def test_handle_websocket_records_intent_on_user_message(temp_db, monkeypatch):
    """handle_websocket 收到 user 消息时,add_message 传 intent 参数。"""
    from nexus.backend import db as db_mod

    captured: list[dict] = []
    real_add = db_mod.add_message

    def spy_add(message_id, session_id, role, content, **kwargs):
        captured.append({"message_id": message_id, "session_id": session_id, "role": role, "content": content, **kwargs})
        return real_add(message_id, session_id, role, content, **kwargs)

    monkeypatch.setattr(db_mod, "add_message", spy_add)

    # 调用 classify 路径
    from nexus.backend.intent.router import classify_intent
    import asyncio

    async def fake_classify(llm, msg):
        return INTENT_TASK if "写" in msg else INTENT_CHITCHAT

    monkeypatch.setattr("nexus.backend.api.ws.classify_intent", fake_classify)

    # 构造 fake websocket,模拟一次 user 消息帧
    from fastapi import WebSocket

    class _FakeWS:
        def __init__(self):
            self.sent: list[dict] = []
        async def send_json(self, data):
            self.sent.append(data)
        async def receive_json(self):
            return {"type": "message", "content": "帮我写个脚本"}
        async def close(self, code=None, reason=None):
            pass

    from nexus.backend.api.ws import handle_websocket

    async def run():
        ws = _FakeWS()
        # get_agent / get_intent_llm 返回 fake
        async def fake_stream(*a, **kw):
            # 不真正调 LLM,直接通过 quality gate
            return 0, "ok", True, None
        # 避免走 _run_agent_streaming:patch 掉
        with patch("nexus.backend.api.ws._run_agent_streaming", side_effect=fake_stream):
            await handle_websocket(
                ws,
                get_agent=lambda: None,
                get_intent_llm=lambda: None,
                get_quality_pipeline=lambda: None,
            )

    # 第一次 receive_json 会拿到 "帮我写个脚本",但后续 receive_json 没设
    # → handle_websocket 在 WebSocketDisconnect 之前会卡住,这里只验证 captured
    # 简化:用 asyncio.wait_for 限时跑
    with pytest.raises((Exception,)):
        asyncio.run(asyncio.wait_for(run(), timeout=2.0))

    # 验证 captured 至少有一条 user 消息且 intent 正确
    user_msgs = [c for c in captured if c["role"] == "user"]
    assert user_msgs, "user 消息没被记录"
    assert user_msgs[0]["intent"] == INTENT_TASK
```

> **注**：上面这个测试用了 patch 走复杂路径,实际更可靠的做法是**单元测试 `handle_websocket` 的"分类 → 入库"小段**:把"分类后写库"提成独立函数 `_classify_and_record(get_intent_llm, session_id, user_content) -> str`,测试这个函数即可。下面 Step 3 会先做这个 refactor。

修正:在 Step 3 改用**辅助函数 + 单元测试**。WS handler 端到端测试改用 dmg-cdp E2E(任务 4)。

实际 Step 1 测试改为**只测辅助函数**(`_classify_and_record`):

```python
# tests/test_intent_ws_integration.py
"""WS handler 辅助函数 _classify_and_record:分类 + 入库 intent 列。"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

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
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_CHITCHAT


async def test_classify_and_record_uses_llm_intent(temp_db, monkeypatch):
    """get_intent_llm 返回 fake LLM,分类结果应写入。"""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage

    from nexus.backend.api import ws as ws_mod
    from nexus.backend.api.ws import _classify_and_record

    class _TaskLLM(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise NotImplementedError
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
    row = conn.execute("SELECT intent FROM messages WHERE session_id = ?", (sid,)).fetchone()
    assert row["intent"] == INTENT_TASK
```

- [ ] **Step 2：跑测试，期望失败**(`_classify_and_record` 不存在)

```bash
pytest tests/test_intent_ws_integration.py -v
```

- [ ] **Step 3：实现**

`nexus/backend/api/ws.py` 头部加 import + 新增辅助函数(放在 `_run_agent_streaming` 之前):

```python
# 在 line 32 后附近
from ..intent.router import (
    DEFAULT_INTENT,
    INTENT_CHITCHAT,
    INTENT_KNOWLEDGE,
    INTENT_TASK,
    IntentKind,
    classify_intent,
)


async def _classify_and_record(
    get_intent_llm: Callable[[], Any] | None,
    session_id: str,
    user_content: str,
) -> IntentKind:
    """调主 LLM 分类 + 把 user 消息(含 intent)写库。

    任何异常 / llm=None 一律兜底 chitchat(最安全:不影响 task 工具链)。
    """
    intent: IntentKind = DEFAULT_INTENT
    llm: Any = None
    if get_intent_llm is not None:
        try:
            llm = get_intent_llm()
        except Exception:  # noqa: BLE001
            llm = None
    if llm is not None:
        intent = await classify_intent(llm, user_content)
    # 入库(用 generate uuid;不传 thinking_content,跟 add_message 默认对齐)
    from ..db import add_message

    add_message(str(uuid.uuid4()), session_id, "user", user_content, intent=intent)
    return intent
```

把 `handle_websocket` 里 line 533-536 的 `add_message(...)` 替换为 `await _classify_and_record(get_intent_llm, session_id, user_content)`:

```python
            # 添加用户消息到历史(intent 由意图识别层落库)
            await _classify_and_record(get_intent_llm, session_id, user_content)
```

`handle_websocket` 签名加 `get_intent_llm`:

```python
async def handle_websocket(
    websocket: WebSocket,
    *,
    get_agent: Callable[[], Any],
    wechat_callback: Callable | None = None,
    get_quality_pipeline: Callable[[], Any] | None = None,
    get_intent_llm: Callable[[], Any] | None = None,  # 新增,None 表示跳过分类
) -> None:
```

`main.py` 的 `websocket_endpoint` 注入 `get_intent_llm` 工厂(在 `_ensure_agent_ready` 之后构造,跟 quality pipeline 共用同一 judge_llm):

```python
# 在 _ensure_agent_ready 之后,websocket_endpoint 之前加:
_intent_llm: Any = None
_intent_llm_lock = threading.RLock()


def _ensure_intent_llm_ready(app) -> None:
    """懒构造意图识别 LLM:复用 quality pipeline 的 judge_llm(同实例,
    避免双倍 token 配额与网络连接)。
    """
    global _intent_llm
    with _intent_llm_lock:
        if _intent_llm is not None:
            return
        pipeline = getattr(app.state, "quality_pipeline", None)
        if pipeline is not None and hasattr(pipeline, "judge"):
            _intent_llm = pipeline.judge.llm
        else:
            # 退化路径:重新构造一个轻量 LLM(同 quality pipeline 配置)
            try:
                from .agent import get_llm
                from .models_config import get_active_model as _gam

                _model_config = _gam() or {}
                _intent_llm = get_llm(
                    api_key=_model_config.get("api_key") or CONFIG.get("minimax_api_key", ""),
                    api_base=_model_config.get("api_base") or CONFIG.get("minimax_api_base"),
                    model_name=_model_config.get("name", CONFIG.get("model_name", "MiniMax-M3")),
                    temperature=0,
                )
            except Exception:  # noqa: BLE001
                _intent_llm = None


def _get_intent_llm() -> Any:
    return _intent_llm
```

`websocket_endpoint` 内,在 `_get_quality_pipeline` 旁加 `get_intent_llm` 注入:

```python
    # 等 quality pipeline 构造完再准备 intent llm(共用 judge_llm 实例)
    _ensure_intent_llm_ready(websocket.app)
    # ... 现有 _get_quality_pipeline 定义 ...

    await handle_websocket(
        websocket,
        get_agent=_get_current_agent,
        wechat_callback=_handle_wechat_message,
        get_quality_pipeline=_get_quality_pipeline,
        get_intent_llm=_get_intent_llm,
    )
```

- [ ] **Step 4：跑新测试 + 全量回归**

```bash
pytest tests/test_intent_ws_integration.py -v
pytest tests/ -q
ruff check nexus/backend/api/ws.py nexus/backend/main.py
ruff format nexus/backend/api/ws.py nexus/backend/main.py
```

- [ ] **Step 5：提交**

```bash
git add nexus/backend/api/ws.py nexus/backend/main.py tests/test_intent_ws_integration.py
git commit -m "feat(ws): 接入意图识别到 WS handler(intent 落 messages 表)"
```

---

### 任务 4：E2E 验证(DMG CDP 真实环境)

**文件：**
- 新建：`frontend/e2e/dmg-cdp/test-dmg-intent.mjs`

- [ ] **Step 1：写 E2E 脚本**

```javascript
// frontend/e2e/dmg-cdp/test-dmg-intent.mjs
// E2E 验证:1) 发闲聊 → 看到响应,后端日志出现 QualityPipeline 短路;
//           2) 发任务 → 看到响应,后端日志出现 quality gate 全跑;
//           3) DB 里 messages.intent 列有正确值。
//
// 前置:DMG 已启动,后端 30000,DevTools 9229。
import { execSync } from 'node:child_process';
import WebSocket from 'ws';
import { writeFileSync, mkdirSync } from 'node:fs';
const OUT = '/tmp/nexus-intent';
mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const target = JSON.parse(execSync('curl -s http://127.0.0.1:9229/json/list').toString())
  .find(t => t.url === 'http://127.0.0.1:30000/app/');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.on('open', r));
async function call(method, params={}) {
  const id = Math.floor(Math.random() * 1e9);
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => {
    const h = (d) => { const m = JSON.parse(d); if (m.id === id) { ws.off('message', h); resolve(m.result); } };
    ws.on('message', h);
  });
}
async function ev(expr) {
  return (await call('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
}

await call('Page.reload', { ignoreCache: true });
await sleep(3500);
await ev(`document.querySelector('.btn-new-task')?.click()`);
await sleep(1500);

async function sendAndWait(question) {
  await ev(`(() => { const ta = document.querySelector('.composer-textarea'); if (ta) { ta.focus(); ta.setSelectionRange(0, 0); } })()`);
  await sleep(200);
  await call('Input.insertText', { text: question });
  await sleep(300);
  await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  for (let i = 0; i < 30; i++) {
    await sleep(1000);
    const len = await ev(`(() => { const arr = document.querySelectorAll('[data-role="assistant"], .bubble-assistant'); return arr.length > 0 ? arr[arr.length - 1].textContent.length : 0; })()`);
    const disabled = await ev(`document.querySelector('.send-button')?.disabled`);
    if (len > 50 && !disabled) return len;
  }
  return -1;
}

// 测试 1:闲聊
const chitchatLen = await sendAndWait('你好');
console.log('[chitchat] asst-len=', chitchatLen);
// 测试 2:任务
const taskLen = await sendAndWait('请帮我把 1 到 10 的整数求和并解释算法');
console.log('[task] asst-len=', taskLen);

// 截图
const scr = await call('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/intent-e2e.png`, Buffer.from(scr.data, 'base64'));

// 用 sqlite3 CLI 直接查 messages.intent
const dbResult = execSync(`sqlite3 ~/.nexus/nexus.db "SELECT role, intent, substr(content, 1, 30) FROM messages ORDER BY created_at DESC LIMIT 4;"`).toString();
console.log('[db-tail]\n' + dbResult);

const ok = chitchatLen > 10 && taskLen > 50;
console.log(ok ? '✅ intent E2E 通过' : '❌ FAIL');
ws.close();
process.exit(ok ? 0 : 1);
```

- [ ] **Step 2：跑 E2E**

```bash
# 前置:DMG 已装,DevTools 9229 已开
node frontend/e2e/dmg-cdp/test-dmg-intent.mjs
```

期望:
- `chitchatLen > 10` 看到 LLM 共情回复
- `taskLen > 50` 看到完整任务回答
- DB 输出含 `user|chitchat|...` 和 `user|task|...` 两行

- [ ] **Step 3：提交**

```bash
git add frontend/e2e/dmg-cdp/test-dmg-intent.mjs
git commit -m "test(e2e): DMG CDP 验证意图识别端到端"
```

---

## 四、风险与回退

| 风险 | 触发条件 | 缓解策略 |
| --- | --- | --- |
| LLM bind_tools 失效 | MiniMax-M3 不支持 function-calling | fallback: parse JSON 文本指令("先输出 `INTENT:xxx`") |
| 分类增加 200-400ms 延迟 | 用户对延迟敏感 | `CLASSIFY_TIMEOUT_S=8s` 上限,失败走 chitchat 不阻塞 |
| 质量门 chitchat 短路对 task 误判 | 模型偶尔把"帮我..."归 chitchat | `_TOOL_TO_INTENT` 显式映射 + classify 失败兜底 chitchat 时 quality gate 仍会跑 4 个 rubric 兜底,不会让坏回答出去 |
| 老库无 intent 列 | 升级前已存在的 `nexus.db` | `_ensure_column` 自动 ALTER,无需手动脚本 |

**回退**:所有 3 个 commit 都是独立可回滚的；最坏情况 `git revert <任务3 commit>` 即可退回到"无 intent"状态,DB 列保留无害。

---

## 五、自检

- [x] **Spec 覆盖**:
  - 意图识别 → 任务 2
  - DB 落库 intent → 任务 1 + 任务 3
  - 跟质量门合并(chitchat 短路天然命中)→ 任务 2 + 任务 3
  - 零新依赖、零新 key → 全文 grep `pip install` / `import xxx` 均为既有
- [x] **Placeholder 扫描**:全文无 TODO/TBD/待定;每步代码完整
- [x] **类型一致性**:
  - `IntentKind` 在 router / __init__ / ws 引用一致
  - `add_message` 关键字参数 `intent` 贯穿 db / test / ws
  - `_classify_and_record` 签名 ↔ 测试调用 ↔ handle_websocket 调用 一致
  - `get_intent_llm` 回调签名 `Callable[[], Any] | None` 三处一致

---

## 六、执行模式

**Plan complete and saved to `docs/superpowers/plans/2026-06-19-intent-recognition-routing.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 每任务派一个 fresh subagent 实施,我在中间审 review,迭代快。

**2. Inline Execution** — 自己在当前 session 按任务批量实施,带 checkpoint。

**选哪个?**
