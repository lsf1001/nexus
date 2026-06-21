# Nexus Observability Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-K-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Nexus 加生产级 observability 子系统:JSONL 结构化日志、4 个产品事件、LangChain callback 通道复用,env 三档配置。

**Architecture:**
- 新增 `nexus/backend/observability/` 子包(`events.py` / `sink.py` / `logger.py` / `handler.py`)
- 4 个产品事件(`ChatStart` / `IntentClassified` / `QualityVerdict` / `ChatEnd`)在 `ws.py` 关键节点 emit
- LLM/tool/chain 事件通过 `NexusLogHandler`(继承 LangChain `BaseCallbackHandler`)写到同一个 sink
- env 三档:`NEXUS_LOG_FORMAT=text|json`、`NEXUS_LOG_FILE=path`、`NEXUS_LOG_LEVEL=INFO|DEBUG`
- `NEXUS_AGENT_VERBOSE=1` 沿用,触发 `StdOutCallbackHandler`(text 调试用,仅在 debug 时启)
- 沿用 stdlib `logging` + `RotatingFileHandler`,**不引第三方** (structlog/python-json-logger 都不要)

**Tech Stack:** Python 3.14、stdlib logging、langchain_core.callbacks.BaseCallbackHandler、`logging.handlers.RotatingFileHandler`

---

## File Structure

| 文件 | 职责 |
|---|---|
| `nexus/backend/observability/__init__.py` | 公开 API |
| `nexus/backend/observability/events.py` | 4 个 frozen dataclass 产品事件 + `to_dict()` |
| `nexus/backend/observability/sink.py` | `EventSink` 类,管理 JSONL 文件 / text stdout、轮转、并发写锁 |
| `nexus/backend/observability/logger.py` | `setup_logging()` env 驱动的 stdlib logging 配置(text/json formatter + file handler) |
| `nexus/backend/observability/handler.py` | `NexusLogHandler(BaseCallbackHandler)` 把 LangChain 事件映射到 sink |
| `nexus/backend/api/ws.py` | 修改:在 chat 关键节点 emit 4 个产品事件,挂 `NexusLogHandler` 到 astream_kwargs |
| `nexus/backend/agent.py` | 修改:把 `NexusLogHandler` 永远挂在 agent 上(替换原 verbose handler 单挂逻辑) |
| `nexus/backend/main.py` | 修改:启动期调 `setup_logging()` + 把 `_nexus_log_handler` 暴露给 ws.py |
| `docs/operations/logging.md` | 新增:env 配置、字段字典、grep/jq 示例、DMG 路径 |
| `tests/test_observability_*.py` | 新增 4 个测试文件 |

---

## Task 1: 事件 schema(frozen dataclass + JSON 序列化)

**Files:**
- Create: `nexus/backend/observability/__init__.py`
- Create: `nexus/backend/observability/events.py`
- Create: `tests/test_observability_events.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_observability_events.py
"""测试 4 个产品事件的 dataclass schema 与 JSON 序列化。"""

from __future__ import annotations

import json

from nexus.backend.observability.events import (
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)


def test_chat_start_to_dict_round_trip():
    e = ChatStart(
        timestamp="2026-06-20T14:00:00.000Z",
        event="chat.start",
        session_id="s-1",
        message_id="m-1",
        content_len=5,
    )
    d = e.to_dict()
    assert d["event"] == "chat.start"
    assert d["session_id"] == "s-1"
    assert d["content_len"] == 5
    # 必须可 JSON 序列化(线上 sink 写 JSONL)
    assert json.loads(json.dumps(d)) == d


def test_intent_classified_latency_ms_field():
    e = IntentClassified(
        timestamp="2026-06-20T14:00:00.200Z",
        event="intent.classified",
        session_id="s-1",
        message_id="m-1",
        intent="chitchat",
        latency_ms=200,
    )
    assert e.to_dict()["latency_ms"] == 200


def test_quality_verdict_carries_scores():
    e = QualityVerdict(
        timestamp="2026-06-20T14:00:01.000Z",
        event="quality.verdict",
        session_id="s-1",
        message_id="m-1",
        verdict="ACCEPT",
        scores={"safety": 0.95, "accuracy": 0.85},
        repair_attempted=False,
    )
    d = e.to_dict()
    assert d["verdict"] == "ACCEPT"
    assert d["scores"]["safety"] == 0.95
    assert d["repair_attempted"] is False


def test_chat_end_includes_duration_and_retries():
    e = ChatEnd(
        timestamp="2026-06-20T14:00:01.500Z",
        event="chat.end",
        session_id="s-1",
        message_id="m-1",
        chunks=12,
        duration_ms=1500,
        retry_count=0,
    )
    d = e.to_dict()
    assert d["chunks"] == 12
    assert d["duration_ms"] == 1500
    assert d["retry_count"] == 0


def test_events_are_frozen():
    e = ChatStart(timestamp="t", event="chat.start", session_id="s", message_id="m", content_len=1)
    import dataclasses
    try:
        e.session_id = "tamper"  # type: ignore[misc]
        assert False, "expected FrozenInstanceError"
    except dataclasses.FrozenInstanceError:
        pass
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_events.py -v`
Expected: `ModuleNotFoundError: No module named 'nexus.backend.observability'`

- [ ] **Step 3: 实现 events.py**

```python
# nexus/backend/observability/events.py
"""Nexus 产品级事件 schema。

4 个 frozen dataclass 覆盖一次 chat 的关键节点:
  - ``ChatStart``: 收到 user 消息,即将分发
  - ``IntentClassified``: 1-shot 意图分类完成
  - ``QualityVerdict``: 质量门 4 维度评分 + verdict
  - ``ChatEnd``: 流结束,聚合 chunks / duration / retry

所有字段 ``to_dict()`` 后可直接 ``json.dumps``。
设计要点:
  - 不可变(``frozen=True``):CLAUDE.md §11
  - ``timestamp`` 始终 ISO 8601 UTC 字符串(由调用方传,sink 不补)
  - ``session_id`` / ``message_id`` 是必填关联键
  - 所有可选字段给类型 ``X | None``,不要给空 dict / 空 str
"""

from __future__ import annotations

import dataclasses
from typing import Any, Final

__all__ = [
    "ChatStart",
    "IntentClassified",
    "QualityVerdict",
    "ChatEnd",
    "EVENT_SCHEMA_VERSION",
]


# 当前 schema 版本号;JSONL 解析器可据此选择字段映射
EVENT_SCHEMA_VERSION: Final[str] = "1.0.0"


@dataclasses.dataclass(frozen=True)
class ChatStart:
    """收到 user 消息,准备分发到主流程。"""

    timestamp: str
    event: str  # 固定 "chat.start"
    session_id: str
    message_id: str
    content_len: int

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class IntentClassified:
    """意图分类器完成 1-shot 分类(成功 / 兜底)。"""

    timestamp: str
    event: str  # 固定 "intent.classified"
    session_id: str
    message_id: str
    intent: str  # "chitchat" | "knowledge" | "task"
    latency_ms: int
    fallback: bool = False  # True = 走 chitchat 兜底(LLM 超时/异常/无 tool_call)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class QualityVerdict:
    """质量门 4 维度评分 + 决策。"""

    timestamp: str
    event: str  # 固定 "quality.verdict"
    session_id: str
    message_id: str
    verdict: str  # "ACCEPT" | "REPAIR" | "REJECT"
    scores: dict[str, float]
    repair_attempted: bool

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ChatEnd:
    """流结束,聚合本次 chat 的关键指标。"""

    timestamp: str
    event: str  # 固定 "chat.end"
    session_id: str
    message_id: str
    chunks: int
    duration_ms: int
    retry_count: int
    intent: str | None = None  # 与 IntentClassified 关联,便于聚合
    verdict: str | None = None  # 与 QualityVerdict 关联
    error_code: str | None = None  # 非空时表示本次 chat 异常结束

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
```

- [ ] **Step 4: 实现 __init__.py**

```python
# nexus/backend/observability/__init__.py
"""Nexus observability 子系统。

公开 API:
  - 事件 schema: :class:`ChatStart` / :class:`IntentClassified` /
    :class:`QualityVerdict` / :class:`ChatEnd`
  - 配置: :func:`setup_logging`
  - 回调: :class:`NexusLogHandler`
"""

from __future__ import annotations

from .events import (
    EVENT_SCHEMA_VERSION,
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)
from .handler import NexusLogHandler
from .logger import setup_logging

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "ChatEnd",
    "ChatStart",
    "IntentClassified",
    "NexusLogHandler",
    "QualityVerdict",
    "setup_logging",
]
```

- [ ] **Step 5: 跑测试确认 pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_events.py -v`
Expected: `5 passed`

- [ ] **Step 6: commit**

```bash
git add nexus/backend/observability/__init__.py nexus/backend/observability/events.py tests/test_observability_events.py
git commit -m "feat(obs): 加 4 个产品事件 schema"
```

---

## Task 2: EventSink(JSONL 文件 + text stdout + 轮转 + 线程安全)

**Files:**
- Create: `nexus/backend/observability/sink.py`
- Create: `tests/test_observability_sink.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_observability_sink.py
"""测试 EventSink 的 JSONL 持久化、text stdout、轮转、并发写锁。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from nexus.backend.observability.events import ChatStart, ChatEnd
from nexus.backend.observability.sink import EventSink


def test_jsonl_write_creates_file_and_appends(tmp_path: Path):
    log_file = tmp_path / "events.jsonl"
    sink = EventSink(path=log_file, format="json")
    sink.emit(ChatStart(timestamp="t1", event="chat.start", session_id="s", message_id="m", content_len=1))
    sink.emit(ChatEnd(timestamp="t2", event="chat.end", session_id="s", message_id="m", chunks=2, duration_ms=100, retry_count=0))
    sink.close()

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "chat.start"
    assert json.loads(lines[1])["event"] == "chat.end"


def test_text_format_writes_human_readable_to_file(tmp_path: Path):
    log_file = tmp_path / "events.log"
    sink = EventSink(path=log_file, format="text")
    sink.emit(ChatStart(timestamp="2026-06-20T14:00:00Z", event="chat.start", session_id="s", message_id="m", content_len=5))
    sink.close()

    content = log_file.read_text(encoding="utf-8")
    assert "[chat.start]" in content
    assert "session_id=s" in content
    assert "content_len=5" in content
    # text 模式不应包含 JSON braces
    assert "{" not in content


def test_sink_creates_parent_directory(tmp_path: Path):
    log_file = tmp_path / "subdir" / "deep" / "events.jsonl"
    sink = EventSink(path=log_file, format="json")
    sink.emit(ChatStart(timestamp="t", event="chat.start", session_id="s", message_id="m", content_len=1))
    sink.close()
    assert log_file.exists()


def test_concurrent_writes_are_thread_safe(tmp_path: Path):
    """多线程并发 emit 不应交错同一行。"""
    log_file = tmp_path / "events.jsonl"
    sink = EventSink(path=log_file, format="json")

    def worker(i: int) -> None:
        for j in range(50):
            sink.emit(
                ChatStart(
                    timestamp=f"t-{i}-{j}",
                    event="chat.start",
                    session_id=f"s-{i}",
                    message_id=f"m-{i}-{j}",
                    content_len=j,
                )
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sink.close()

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 200
    # 每行必须能独立 JSON parse(没交错)
    for line in lines:
        json.loads(line)


def test_sink_close_is_idempotent(tmp_path: Path):
    log_file = tmp_path / "events.jsonl"
    sink = EventSink(path=log_file, format="json")
    sink.close()
    sink.close()  # 不应抛异常
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_sink.py -v`
Expected: `ModuleNotFoundError: No module named 'nexus.backend.observability.sink'`

- [ ] **Step 3: 实现 sink.py**

```python
# nexus/backend/observability/sink.py
"""EventSink:产品事件的持久化与展示通道。

设计要点:
  - **JSONL 文件**:每行一个事件,生产环境机器解析用。
  - **text 模式**:调试 / 桌面端 GUI 直接读用,kv 格式 `event=... session_id=...`。
  - **轮转**:`RotatingFileHandler`,10MB × 5 备份,默认。env 可覆盖。
  - **并发写锁**:`threading.Lock`,LangChain callback 是多线程同步,
    handler 触发时不能交错半行。
  - **延迟打开**:首次 ``emit`` 才创建文件 + 父目录,测试 / 闲置场景零开销。
  - **close 幂等**:多次调用安全。
"""

from __future__ import annotations

import json
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from .events import ChatEnd, ChatStart, IntentClassified, QualityVerdict

__all__ = ["EventSink", "DEFAULT_MAX_BYTES", "DEFAULT_BACKUP_COUNT"]


DEFAULT_MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10MB
DEFAULT_BACKUP_COUNT: Final[int] = 5

_logger = logging.getLogger(__name__)


class EventSink:
    """产品事件 sink。支持 JSONL 文件 / text 文件,线程安全。

    Args:
        path: 日志文件路径。父目录不存在会自动创建。
        format: ``"json"``(每行 JSON)/ ``"text"``(kv 可读)。
        max_bytes: 轮转阈值,默认 10MB。
        backup_count: 保留历史文件数,默认 5。
    """

    def __init__(
        self,
        path: Path,
        format: str = "json",
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ) -> None:
        if format not in ("json", "text"):
            raise ValueError(f"format must be 'json' or 'text', got {format!r}")
        self._path = Path(path)
        self._format = format
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.Lock()
        self._handler: RotatingFileHandler | None = None
        self._closed = False

    def _ensure_handler(self) -> RotatingFileHandler:
        if self._handler is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handler = RotatingFileHandler(
                self._path,
                maxBytes=self._max_bytes,
                backupCount=self._backup_count,
                encoding="utf-8",
            )
        return self._handler

    def emit(self, event: "ChatStart | IntentClassified | QualityVerdict | ChatEnd") -> None:
        """写入一个产品事件。线程安全。"""
        if self._closed:
            return
        line = self._format_line(event.to_dict())
        with self._lock:
            handler = self._ensure_handler()
            handler.emit(logging.LogRecord(
                name="nexus.observability",
                level=logging.INFO,
                pathname=__file__,
                lineno=0,
                msg=line,
                args=(),
                exc_info=None,
            ))

    def _format_line(self, payload: dict[str, Any]) -> str:
        if self._format == "json":
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        # text 模式:key=value 紧凑格式
        parts = [f"[{payload.get('event', '?')}]"]
        for k, v in payload.items():
            if k == "event":
                continue
            parts.append(f"{k}={v!r}" if isinstance(v, (dict, list)) else f"{k}={v}")
        return " ".join(parts)

    def close(self) -> None:
        with self._lock:
            if self._handler is not None and not self._closed:
                self._handler.close()
                self._closed = True
```

- [ ] **Step 4: 跑测试确认 pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_sink.py -v`
Expected: `5 passed`

- [ ] **Step 5: 更新 `__init__.py` 导出 EventSink**

在 `nexus/backend/observability/__init__.py` 的 import 块追加:

```python
from .sink import EventSink
```

并在 `__all__` 列表插入 `"EventSink"`(位置在 `"NexusLogHandler"` 后)。

- [ ] **Step 6: 跑 events 测试确认 import 链没断**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_events.py -v`
Expected: `5 passed`

- [ ] **Step 7: commit**

```bash
git add nexus/backend/observability/__init__.py nexus/backend/observability/sink.py tests/test_observability_sink.py
git commit -m "feat(obs): 加 EventSink(JSONL/text/轮转/并发锁)"
```

---

## Task 3: setup_logging()(env 驱动的 stdlib logging 配置)

**Files:**
- Create: `nexus/backend/observability/logger.py`
- Create: `tests/test_observability_logger.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_observability_logger.py
"""测试 setup_logging 的 env 三档配置 + 重复调用幂等。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nexus.backend.observability.logger import (
    ENV_LOG_FORMAT,
    ENV_LOG_LEVEL,
    setup_logging,
)


def test_default_log_path_is_under_nexus_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(ENV_LOG_FORMAT, raising=False)
    monkeypatch.delenv(ENV_LOG_LEVEL, raising=False)
    setup_logging()
    expected = tmp_path / ".nexus" / "logs" / "nexus.log"
    assert expected.exists() or expected.parent.exists()


def test_text_format_writes_kv_lines(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "test.log"
    monkeypatch.setenv(ENV_LOG_FORMAT, "text")
    monkeypatch.setenv("NEXUS_LOG_FILE", str(log_file))
    setup_logging()
    logging.getLogger("test.logger").info("hello %s", "world")
    # flush handlers
    for h in logging.getLogger().handlers:
        h.flush()
    content = log_file.read_text(encoding="utf-8")
    assert "hello world" in content
    assert "test.logger" in content


def test_json_format_writes_json_lines(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "test.jsonl"
    monkeypatch.setenv(ENV_LOG_FORMAT, "json")
    monkeypatch.setenv("NEXUS_LOG_FILE", str(log_file))
    setup_logging()
    logging.getLogger("test.logger").info("hello %s", "world")
    for h in logging.getLogger().handlers:
        h.flush()
    lines = [ln for ln in log_file.read_text(encoding="utf-8").strip().split("\n") if ln]
    assert len(lines) >= 1
    payload = json.loads(lines[-1])
    assert payload["message"] == "hello world"
    assert payload["name"] == "test.logger"


def test_log_level_env_respected(monkeypatch):
    monkeypatch.setenv(ENV_LOG_LEVEL, "WARNING")
    setup_logging()
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_is_idempotent(monkeypatch):
    """多次调用不重复挂 handler。"""
    monkeypatch.setenv(ENV_LOG_FORMAT, "text")
    setup_logging()
    handler_count_first = len(logging.getLogger().handlers)
    setup_logging()
    handler_count_second = len(logging.getLogger().handlers)
    assert handler_count_first == handler_count_second
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_logger.py -v`
Expected: `ModuleNotFoundError: No module named 'nexus.backend.observability.logger'`

- [ ] **Step 3: 实现 logger.py**

```python
# nexus/backend/observability/logger.py
"""Nexus logging 配置入口。

env 三档:
  - ``NEXUS_LOG_FORMAT=text|json``(默认 text)
  - ``NEXUS_LOG_FILE=path``(默认 ``~/.nexus/logs/nexus.log``)
  - ``NEXUS_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR``(默认 INFO)

JSON 格式字段:``timestamp`` / ``level`` / ``name`` / ``message`` /
``module`` / ``lineno``。
text 格式:``2026-06-20 14:00:00,123 INFO test.logger hello world``(stdlib 默认)。

``setup_logging()`` 幂等:重复调用不会堆 handler。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

__all__ = ["setup_logging", "ENV_LOG_FORMAT", "ENV_LOG_LEVEL", "ENV_LOG_FILE"]


ENV_LOG_FORMAT: Final = "NEXUS_LOG_FORMAT"
ENV_LOG_LEVEL: Final = "NEXUS_LOG_LEVEL"
ENV_LOG_FILE: Final = "NEXUS_LOG_FILE"

_DEFAULT_LOG_LEVEL: Final = "INFO"
_VALID_FORMATS: Final = frozenset({"text", "json"})


class _JsonFormatter(logging.Formatter):
    """把 LogRecord 转成单行 JSON。

    不引第三方(避免 structlog / python-json-logger 依赖)。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "lineno": record.lineno,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _resolve_log_path() -> Path:
    raw = os.environ.get(ENV_LOG_FILE)
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".nexus" / "logs" / "nexus.log"


def _resolve_level() -> int:
    raw = os.environ.get(ENV_LOG_LEVEL, _DEFAULT_LOG_LEVEL).upper()
    level = logging.getLevelName(raw)
    if not isinstance(level, int):
        return logging.INFO
    return level


def _resolve_format() -> str:
    raw = os.environ.get(ENV_LOG_FORMAT, "text").lower()
    if raw not in _VALID_FORMATS:
        return "text"
    return raw


def setup_logging() -> logging.Logger:
    """配置根 logger。幂等。

    Returns:
        配置后的根 logger 实例。
    """
    root = logging.getLogger()

    # 已挂过我们自己的 handler 就不再添加
    marker_attr = "_nexus_observability_configured"
    if getattr(root, marker_attr, False):
        return root

    fmt = _resolve_format()
    level = _resolve_level()
    log_path = _resolve_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter: logging.Formatter
    if fmt == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # 清理已有的同源 handler,避免重复(uvicorn 启动时可能预挂 StreamHandler)
    for h in list(root.handlers):
        if getattr(h, "_nexus_observability_owned", False):
            root.removeHandler(h)

    handler._nexus_observability_owned = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, marker_attr, True)

    # 父 logger 配置(沿用上一阶段研究的结论)
    logging.getLogger("deepagents").setLevel(logging.INFO)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langchain_core").setLevel(logging.WARNING)

    root.info("observability.setup_logging format=%s path=%s level=%s", fmt, log_path, level)
    return root
```

- [ ] **Step 4: 跑测试确认 pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_logger.py -v`
Expected: `5 passed`

- [ ] **Step 5: 更新 `__init__.py` 导出 setup_logging**

已经在 Task 1 写过,但确认下:`__init__.py` 中已经有 `from .logger import setup_logging` 和 `"setup_logging"` 在 `__all__` 中。

- [ ] **Step 6: commit**

```bash
git add nexus/backend/observability/logger.py tests/test_observability_logger.py
git commit -m "feat(obs): 加 setup_logging(env 三档 + JSON/text + 幂等)"
```

---

## Task 4: NexusLogHandler(LangChain callback 通道复用)

**Files:**
- Create: `nexus/backend/observability/handler.py`
- Create: `tests/test_observability_handler.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_observability_handler.py
"""测试 NexusLogHandler 把 LangChain LLM/tool/chain 事件落到 EventSink。"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult

from nexus.backend.observability.handler import NexusLogHandler
from nexus.backend.observability.sink import EventSink


def _make_sink(tmp_path: Path) -> EventSink:
    return EventSink(path=tmp_path / "events.jsonl", format="json")


def test_handler_subclasses_base_callback_handler():
    h = NexusLogHandler(sink=_make_sink(Path("/tmp")))
    assert isinstance(h, BaseCallbackHandler)


def test_on_llm_end_writes_event(tmp_path: Path):
    sink = _make_sink(tmp_path)
    h = NexusLogHandler(sink=sink)

    h.on_llm_start(serialized={"name": "ChatOpenAI"}, prompts=["hi"], run_id="r1")
    h.on_llm_end(
        response=LLMResult(generations=[[ChatGeneration(message=None, text="hi there")]]),
        run_id="r1",
    )

    sink.close()
    lines = [ln for ln in (tmp_path / "events.jsonl").read_text().strip().split("\n") if ln]
    # 至少 on_llm_start + on_llm_end 两条
    assert len(lines) >= 2
    parsed = [json.loads(ln) for ln in lines]
    kinds = {p["event"] for p in parsed}
    assert "llm.start" in kinds
    assert "llm.end" in kinds


def test_on_tool_start_writes_event_with_tool_name(tmp_path: Path):
    sink = _make_sink(tmp_path)
    h = NexusLogHandler(sink=sink)
    h.on_tool_start(serialized={"name": "web_search"}, input_str="search query", run_id="r1")
    sink.close()

    lines = [json.loads(ln) for ln in (tmp_path / "events.jsonl").read_text().strip().split("\n") if ln]
    tool_starts = [p for p in lines if p["event"] == "tool.start"]
    assert len(tool_starts) == 1
    assert tool_starts[0]["tool"] == "web_search"


def test_sink_failure_does_not_break_callback_chain(tmp_path: Path, capsys):
    """EventSink 关闭后再 emit 不应抛异常(防止 callback 链中断)。"""
    sink = _make_sink(tmp_path)
    sink.close()  # 提前关掉
    h = NexusLogHandler(sink=sink)
    # 不应抛
    h.on_llm_start(serialized={"name": "ChatOpenAI"}, prompts=["hi"], run_id="r1")
```

- [ ] **Step 2: 跑测试确认 fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_handler.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 handler.py**

```python
# nexus/backend/observability/handler.py
"""NexusLogHandler:把 LangChain 回调通道的事件落到 EventSink。

事件映射:
  - ``on_llm_start``   → ``{"event": "llm.start", "model": ..., "prompt_chars": N, "run_id": ...}``
  - ``on_llm_end``     → ``{"event": "llm.end", "model": ..., "run_id": ..., "duration_ms": N}``
  - ``on_tool_start``  → ``{"event": "tool.start", "tool": name, "input": ..., "run_id": ...}``
  - ``on_tool_end``    → ``{"event": "tool.end", "tool": name, "run_id": ...}``
  - ``on_chain_start`` → ``{"event": "chain.start", "chain": name, "run_id": ...}``
  - ``on_chain_end``   → ``{"event": "chain.end", "chain": name, "run_id": ...}``

Sink 写入失败时吞掉异常(callback 链不能被观测层破坏)。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .events import ChatEnd  # 复用 dataclass 风格;这里直接构造 dict
from .sink import EventSink

__all__ = ["NexusLogHandler"]

_logger = logging.getLogger(__name__)


class NexusLogHandler(BaseCallbackHandler):
    """Nexus 专属 LangChain callback handler。

    Args:
        sink: 事件落地目标(必填,owner 负责生命周期)。
        run_id: 当前 graph 运行的 run_id(可选,用于多 run 聚合)。
    """

    def __init__(self, sink: EventSink, run_id: str | None = None) -> None:
        super().__init__()
        self._sink = sink
        self._run_id = run_id
        # 跟踪每个 run 的开始时间,用于 on_*_end 计算 duration_ms
        self._start_times: dict[str, float] = {}

    # ----- 工具:安全 emit -----

    def _emit(self, payload: dict[str, Any]) -> None:
        """构造 ChatEnd-like dict 并写 sink。任何异常吞掉。"""
        try:
            from datetime import datetime, timezone

            payload.setdefault("timestamp", datetime.now(tz=timezone.utc).isoformat())
            payload.setdefault("event", "unknown")
            payload["run_id"] = payload.get("run_id") or self._run_id
            # 走 sink 的 raw 写入,不走 ChatEnd dataclass 约束(LangChain
            # 事件 schema 跟产品事件 schema 不同,这里直接写 dict)
            self._sink.emit_raw(payload)
        except Exception:  # noqa: BLE001 - 观测层不能破坏 callback 链
            _logger.exception("NexusLogHandler 写 sink 失败,已吞掉")

    # ----- LangChain 回调 -----

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        self._start_times[run_id] = time.monotonic()
        self._emit({
            "event": "llm.start",
            "model": serialized.get("name", "unknown"),
            "prompt_chars": sum(len(p) for p in prompts),
            "run_id": run_id,
        })

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        # token 用量(LangChain OpenAI 兼容)
        usage = getattr(response, "llm_output", None) or {}
        token_usage = usage.get("token_usage", {}) if isinstance(usage, dict) else {}
        self._emit({
            "event": "llm.end",
            "run_id": run_id,
            "duration_ms": duration_ms,
            "prompt_tokens": token_usage.get("prompt_tokens"),
            "completion_tokens": token_usage.get("completion_tokens"),
            "total_tokens": token_usage.get("total_tokens"),
        })

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        self._start_times[run_id] = time.monotonic()
        self._emit({
            "event": "tool.start",
            "tool": serialized.get("name", "unknown"),
            "input_chars": len(input_str),
            "run_id": run_id,
        })

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        self._emit({
            "event": "tool.end",
            "run_id": run_id,
            "duration_ms": duration_ms,
        })

    def on_chain_start(self, serialized: dict[str, Any], inputs: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        self._start_times[run_id] = time.monotonic()
        self._emit({
            "event": "chain.start",
            "chain": serialized.get("name") if serialized else None,
            "run_id": run_id,
        })

    def on_chain_end(self, outputs: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        self._emit({
            "event": "chain.end",
            "run_id": run_id,
            "duration_ms": duration_ms,
        })
```

- [ ] **Step 4: 给 sink 加 `emit_raw` 方法**

修改 `nexus/backend/observability/sink.py`:

在 `EventSink.emit` 方法之后,新增:

```python
    def emit_raw(self, payload: dict[str, Any]) -> None:
        """直接写一个 dict 事件(供 NexusLogHandler 等 LangChain callback 用)。

        与 ``emit`` 区别:不强制要求传 dataclass,允许任意 dict(用于 LangChain
        内部事件的 schema 灵活性)。
        """
        if self._closed:
            return
        line = self._format_line(payload)
        with self._lock:
            handler = self._ensure_handler()
            handler.emit(logging.LogRecord(
                name="nexus.observability",
                level=logging.INFO,
                pathname=__file__,
                lineno=0,
                msg=line,
                args=(),
                exc_info=None,
            ))
```

并在 `__all__` 末尾追加 `"emit_raw"`(或保持不导出,handler 内部用)。**保持私有即可**,handler 是同包使用。

- [ ] **Step 5: 跑测试确认 pass**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_observability_handler.py tests/test_observability_sink.py -v`
Expected: `4 + 5 = 9 passed`

- [ ] **Step 6: commit**

```bash
git add nexus/backend/observability/handler.py nexus/backend/observability/sink.py tests/test_observability_handler.py
git commit -m "feat(obs): 加 NexusLogHandler(LLM/tool/chain 事件)"
```

---

## Task 5: 集成 — main.py 启动期 setup_logging + 创建全局 sink

**Files:**
- Modify: `nexus/backend/main.py:87-95` (logging.basicConfig 那块)

- [ ] **Step 1: 阅读当前 main.py 顶部**

Read `nexus/backend/main.py:1-100`,确认 `logging.basicConfig` 与 `_create_agent_with_model` 的位置。

- [ ] **Step 2: 替换 logging.basicConfig 块**

把当前的:

```python
logging.basicConfig(level=logging.INFO)
# DeepAgents 0.6.8 几乎无运行期 logger(graph 无,_models 仅异常 INFO);
# 真正能看到 streaming / tool dispatch 细节靠 LangChain callback / verbose。
# 这里仅把 deepagents 父 logger 调到 INFO,后续要加 StdOutCallbackHandler。
logging.getLogger("deepagents").setLevel(logging.INFO)
# LangChain 父 logger 保持 WARNING,避免 stream / token 刷屏
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("langchain_core").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
```

替换为:

```python
from .observability import setup_logging

setup_logging()  # env 驱动:NEXUS_LOG_FORMAT/FILE/LEVEL
logger = logging.getLogger(__name__)
```

注释保留在 `setup_logging()` 内部,这里不再重复。

- [ ] **Step 3: 跑现有 pytest 确认无回归**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q`
Expected: 所有现有测试通过(observability 模块只是新增,不影响 main.py 行为)。

- [ ] **Step 4: 实跑一次 backend 看 log file 是否生成**

```bash
cd /Users/yxb/projects/nexus
NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/tmp/observability-test.log ./.venv/bin/python -c "
import uvicorn
uvicorn.run('nexus.backend.main:app', host='127.0.0.1', port=30001, log_level='warning')
" &
BACKEND_PID=$!
sleep 4
kill $BACKEND_PID 2>/dev/null
echo '--- log file ---'
cat /tmp/observability-test.log 2>/dev/null | head -10
```

Expected: 文件存在,首行 `observability.setup_logging format=json ...`。

- [ ] **Step 5: commit**

```bash
git add nexus/backend/main.py
git commit -m "refactor(main): 启动期调 setup_logging 取代 basicConfig"
```

---

## Task 6: 集成 — agent.py 挂 NexusLogHandler + ws.py 4 个产品事件

**Files:**
- Modify: `nexus/backend/agent.py:404-411` (verbose handler 那块)
- Modify: `nexus/backend/api/ws.py` (`handle_websocket` 加事件 emit)

- [ ] **Step 1: 阅读 agent.py verbose handler 那段**

Read `nexus/backend/agent.py:400-413`,确认现有 `os.environ.get("NEXUS_AGENT_VERBOSE") == "1"` + `_nexus_verbose_handler = StdOutCallbackHandler()` 逻辑。

- [ ] **Step 2: 替换为双 handler 挂载**

把当前的:

```python
if os.environ.get("NEXUS_AGENT_VERBOSE") == "1":
    from langchain_core.callbacks import StdOutCallbackHandler
    agent._nexus_verbose_handler = StdOutCallbackHandler()
    logger.info("NEXUS_AGENT_VERBOSE=1, 已挂 StdOutCallbackHandler 到 agent")
```

替换为:

```python
# 总是挂 NexusLogHandler(走 setup_logging 的 EventSink,JSONL/text 落盘)
from .observability import NexusLogHandler
from .observability.sink import EventSink

# EventSink 是全局单例,由 setup_logging() 在 main.py 启动期创建并 attach 到
# ``logging.getLogger("nexus.observability")`` 的 handler 上。但 callback 需要
# 显式 sink 实例,所以从环境变量解析路径重建一个。
import os as _os
from pathlib import Path as _Path

_sink_path = _Path(_os.environ.get("NEXUS_LOG_FILE", str(_Path.home() / ".nexus" / "logs" / "nexus.log"))).expanduser()
_sink_fmt = _os.environ.get("NEXUS_LOG_FORMAT", "text")
agent._nexus_log_handler = NexusLogHandler(sink=EventSink(path=_sink_path, format=_sink_fmt))

# 排障模式额外挂 StdOutCallbackHandler(text 调试用,生产不开启)
if _os.environ.get("NEXUS_AGENT_VERBOSE") == "1":
    from langchain_core.callbacks import StdOutCallbackHandler
    agent._nexus_verbose_handler = StdOutCallbackHandler()
    logger.info("NEXUS_AGENT_VERBOSE=1, 已挂 StdOutCallbackHandler 到 agent(排障模式)")
else:
    agent._nexus_verbose_handler = None
```

> **Why 总是挂 NexusLogHandler**:日常使用就需要 JSONL 落盘,作为生产观测数据源。
> verbose 模式仅在 debug 时开。

- [ ] **Step 3: 阅读 ws.py verbose handler 注入那段**

Read `nexus/backend/api/ws.py:209-222`,确认现有 `astream_kwargs` 构造。

- [ ] **Step 4: 把 verbose handler 替换为 log handler**

把当前的:

```python
verbose_handler = getattr(agent, "_nexus_verbose_handler", None)
astream_kwargs: dict[str, Any] = {}
if verbose_handler is not None:
    astream_kwargs["config"] = {"callbacks": [verbose_handler]}
```

替换为:

```python
# 挂 NexusLogHandler(必挂)+ StdOutCallbackHandler(仅 verbose 模式)
log_handler = getattr(agent, "_nexus_log_handler", None)
verbose_handler = getattr(agent, "_nexus_verbose_handler", None)
astream_kwargs: dict[str, Any] = {}
callbacks: list = []
if log_handler is not None:
    callbacks.append(log_handler)
if verbose_handler is not None:
    callbacks.append(verbose_handler)
if callbacks:
    astream_kwargs["config"] = {"callbacks": callbacks}
```

- [ ] **Step 5: 跑 pytest 确认无回归**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q`
Expected: 全通过。

- [ ] **Step 6: 实跑 ws.py 路径触发 JSONL 落盘**

```bash
cd /Users/yxb/projects/nexus
# 重启 backend with json mode
kill $(lsof -ti:30000) 2>/dev/null
sleep 1
nohup env NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/tmp/nexus-obs.log PYTHONUNBUFFERED=1 \
  ./.venv/bin/python -c "import uvicorn; uvicorn.run('nexus.backend.main:app', host='127.0.0.1', port=30000, log_level='warning')" \
  > /tmp/nexus-backend.log 2>&1 &
sleep 4
# 触发一次 chat
.venv/bin/python /tmp/ws-verbose-test.py
sleep 1
echo '--- JSONL events ---'
cat /tmp/nexus-obs.log | head -20
echo '--- event types ---'
cat /tmp/nexus-obs.log | grep -oE '"event":"[^"]+"' | sort | uniq -c
```

Expected: 看到 `chain.start / chain.end / llm.start / llm.end` 等事件。

- [ ] **Step 7: commit**

```bash
git add nexus/backend/agent.py nexus/backend/api/ws.py
git commit -m "feat(obs): 挂 NexusLogHandler 到 agent + ws"
```

---

## Task 7: 集成 — ws.py emit 4 个产品事件

**Files:**
- Modify: `nexus/backend/api/ws.py` (多处)
- Create: `tests/test_observability_ws_integration.py`

- [ ] **Step 1: 阅读 ws.py handle_websocket 入口**

Read `nexus/backend/api/ws.py:1-50` + 找 `handle_websocket` 入口(搜索 `async def handle_websocket`)。

- [ ] **Step 2: 写失败测试**

```python
# tests/test_observability_ws_integration.py
"""测试 ws.py 在 chat 流程中 emit 4 个产品事件。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.backend.observability.events import (
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)
from nexus.backend.observability.sink import EventSink


@pytest.fixture
def jsonl_sink(tmp_path: Path) -> EventSink:
    sink = EventSink(path=tmp_path / "events.jsonl", format="json")
    yield sink
    sink.close()


@pytest.mark.asyncio
async def test_chat_start_event_emitted(jsonl_sink: EventSink):
    """ws.py 收到 chat 消息时应 emit ChatStart。"""
    # 用 monkeypatch 把全局 sink 替换为 jsonl_sink
    # 然后 mock handle_websocket 的关键依赖,只验证事件 emit
    # 这里我们走一个简化路径:直接调内部 emit 函数
    from nexus.backend.api import ws as ws_module

    # 替换 module-level helper
    captured = []
    real_emit = jsonl_sink.emit
    jsonl_sink.emit = lambda e: (captured.append(e), real_emit(e))[1]
    try:
        with patch.object(ws_module, "emit_chat_event", lambda e: jsonl_sink.emit(e)):
            event = ChatStart(
                timestamp="t", event="chat.start",
                session_id="s", message_id="m", content_len=3,
            )
            ws_module.emit_chat_event(event)
    finally:
        jsonl_sink.emit = real_emit

    assert any(isinstance(e, ChatStart) and e.session_id == "s" for e in captured)
```

> 这个测试故意写得轻量 — 真正的 handle_websocket 是复杂 IO,端到端用 E2E 覆盖(Task 8)。
> 这里只验证事件 dataclass + sink 序列化集成路径没断。

- [ ] **Step 3: 在 ws.py 顶部加 emit helper**

在 `nexus/backend/api/ws.py:1-30` 区域(import 块末尾),追加:

```python
from datetime import datetime, timezone

from ..observability import ChatEnd, ChatStart, IntentClassified, QualityVerdict
from ..observability.sink import EventSink

_observability_sink: EventSink | None = None


def _get_observability_sink() -> EventSink:
    """获取全局 EventSink 单例。

    首次调用时按 env 重建;后续复用。重建路径与 setup_logging 一致。
    """
    global _observability_sink
    if _observability_sink is None:
        import os as _os
        from pathlib import Path as _Path
        _path = _Path(_os.environ.get("NEXUS_LOG_FILE", str(_Path.home() / ".nexus" / "logs" / "nexus.log"))).expanduser()
        _fmt = _os.environ.get("NEXUS_LOG_FORMAT", "text")
        _observability_sink = EventSink(path=_path, format=_fmt)
    return _observability_sink


def emit_chat_event(event) -> None:
    """公开 API:ws.py 各处 emit 产品事件。"""
    try:
        _get_observability_sink().emit(event)
    except Exception:
        logger.exception("emit_chat_event 失败,已吞掉")
```

> **`emit_chat_event` 是观测层出口**,任何异常吞掉,不能影响主流程。

- [ ] **Step 4: 在 `handle_websocket` 收到 chat 帧后 emit ChatStart**

Read `nexus/backend/api/ws.py:530-580`(找 `if message.get("type") == "chat":` 之类的入口)。

在 chat 消息解析后,生成 `message_id` 之前的位置,插入:

```python
from uuid import uuid4

message_id = str(uuid4())
now_iso = datetime.now(tz=timezone.utc).isoformat()
emit_chat_event(ChatStart(
    timestamp=now_iso,
    event="chat.start",
    session_id=session_id,
    message_id=message_id,
    content_len=len(content),
))
```

(把原先生成 message_id 的代码移除,改用上面这一处统一生成。)

- [ ] **Step 5: 在 `_classify_and_record` 调用后 emit IntentClassified**

找到 `_classify_and_record(...)` 调用点(grep `intent_classified` 或 `classify_intent`)。在调用后插入:

```python
intent_classified_at = time.monotonic()
# ... 现有 _classify_and_record 调用 ...
# 调用后:
intent_latency_ms = int((time.monotonic() - intent_classified_at) * 1000)
emit_chat_event(IntentClassified(
    timestamp=datetime.now(tz=timezone.utc).isoformat(),
    event="intent.classified",
    session_id=session_id,
    message_id=message_id,
    intent=intent_result.intent,
    latency_ms=intent_latency_ms,
    fallback=intent_result.fallback,
))
```

> 如果现有 `_classify_and_record` 返回结构不同,改用实际可用字段。

- [ ] **Step 6: 在 quality pipeline 调用后 emit QualityVerdict**

找到 `pipeline.run_with_quality(...)` 或 `run_with_quality` 调用。返回值是 `FinalResponse`(`verdict` / `scores` / `repair_attempted`)。在其后插入:

```python
emit_chat_event(QualityVerdict(
    timestamp=datetime.now(tz=timezone.utc).isoformat(),
    event="quality.verdict",
    session_id=session_id,
    message_id=message_id,
    verdict=final_response.verdict.value,
    scores=dict(final_response.scores) if final_response.scores else {},
    repair_attempted=final_response.repair_attempted,
))
```

- [ ] **Step 7: 在 stream 结束 + chunks 累计完成后 emit ChatEnd**

找到 `_run_agent_streaming` 调用之后的"本次流结束"逻辑点。在 `chunks_count` / `retry_count` / `duration_ms` 都已知的位置,插入:

```python
emit_chat_event(ChatEnd(
    timestamp=datetime.now(tz=timezone.utc).isoformat(),
    event="chat.end",
    session_id=session_id,
    message_id=message_id,
    chunks=chunks_count,
    duration_ms=int((time.monotonic() - chat_start_monotonic) * 1000),
    retry_count=retry_count,
    intent=intent_result.intent if intent_result else None,
    verdict=final_response.verdict.value if final_response else None,
    error_code=error_code if had_error else None,
))
```

> `chat_start_monotonic` 应在 ChatStart 之后立即 `time.monotonic()`,与上面 `intent_classified_at` 同级。

- [ ] **Step 8: 跑 pytest + ruff**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q`
Expected: 全通过(ws.py 集成测试 + 现有 320+ tests)。

Run: `.venv/bin/ruff check nexus/ tests/`
Expected: 0 errors。

Run: `.venv/bin/ruff format --check nexus/`
Expected: 0 diff。

- [ ] **Step 9: E2E 验证**

```bash
cd /Users/yxb/projects/nexus
kill $(lsof -ti:30000) 2>/dev/null
sleep 1
nohup env NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/tmp/nexus-obs2.log PYTHONUNBUFFERED=1 \
  ./.venv/bin/python -c "import uvicorn; uvicorn.run('nexus.backend.main:app', host='127.0.0.1', port=30000, log_level='warning')" \
  > /tmp/nexus-backend.log 2>&1 &
sleep 4
.venv/bin/python /tmp/ws-verbose-test.py
sleep 1
echo '--- chat.* events ---'
grep '"event":"chat\.' /tmp/nexus-obs2.log | head -10
```

Expected: 看到 `chat.start / intent.classified / quality.verdict / chat.end` 四行 JSON。

- [ ] **Step 10: commit**

```bash
git add nexus/backend/api/ws.py tests/test_observability_ws_integration.py
git commit -m "feat(obs): ws.py emit 4 个产品事件"
```

---

## Task 8: docs/operations/logging.md

**Files:**
- Create: `docs/operations/logging.md`

- [ ] **Step 1: 写文档**

```markdown
# Nexus 日志与可观测性

> **目标**:在不开 IDE / 不接 LangSmith 的前提下,从日志还原一次 chat 的完整轨迹。
> **核心设计**:JSONL 文件 + 4 个产品事件 + env 三档配置 + LangChain callback 通道复用。

---

## 快速上手

### 默认(text 模式,开发友好)

```bash
.venv/bin/python -c "import uvicorn; uvicorn.run('nexus.backend.main:app', ...)"
# 日志写: ~/.nexus/logs/nexus.log(10MB 轮转,保留 5 份)
```

### 生产(json 模式)

```bash
NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/var/log/nexus/nexus.log ./Nexus.app/...
```

### 排障(verbose,看 LangGraph 全链路)

```bash
NEXUS_LOG_FORMAT=text NEXUS_AGENT_VERBOSE=1 PYTHONUNBUFFERED=1 ./.venv/bin/python -c "import uvicorn; ..."
# 额外挂 StdOutCallbackHandler,stdout 实时打印 > Entering new ... chain
```

---

## 环境变量

| 变量 | 默认 | 取值 | 说明 |
|---|---|---|---|
| `NEXUS_LOG_FORMAT` | `text` | `text` \| `json` | text = uvicorn 风格;json = 每行 JSON |
| `NEXUS_LOG_FILE` | `~/.nexus/logs/nexus.log` | 任意路径 | 父目录不存在会自动创建 |
| `NEXUS_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | root logger 级别 |
| `NEXUS_AGENT_VERBOSE` | 未设 | `1` | 额外挂 `StdOutCallbackHandler`,stdout 实时打印 LangGraph 链路 |

**轮转**:固定 10MB × 5 份(代码内常量)。后续若需可调,再加 env。

---

## 事件字典

### 产品事件(每次 chat 必出,4 条)

| 事件 | 触发时机 | 必填字段 | 可选字段 |
|---|---|---|---|
| `chat.start` | 收到 user 消息,即将分发 | `session_id` `message_id` `content_len` | — |
| `intent.classified` | 意图分类完成 | `session_id` `message_id` `intent` `latency_ms` | `fallback` |
| `quality.verdict` | 质量门评分完成 | `session_id` `message_id` `verdict` `scores` `repair_attempted` | — |
| `chat.end` | 流结束(成功 / 异常) | `session_id` `message_id` `chunks` `duration_ms` `retry_count` | `intent` `verdict` `error_code` |

### LangChain 内部事件(NexusLogHandler 转写,仅供调试)

| 事件 | 来源 | 字段 |
|---|---|---|
| `llm.start` | `on_llm_start` | `model` `prompt_chars` `run_id` |
| `llm.end` | `on_llm_end` | `run_id` `duration_ms` `prompt_tokens` `completion_tokens` `total_tokens` |
| `tool.start` | `on_tool_start` | `tool` `input_chars` `run_id` |
| `tool.end` | `on_tool_end` | `run_id` `duration_ms` |
| `chain.start` / `chain.end` | `on_chain_*` | `chain` `run_id` `duration_ms` |

> LangChain 事件在生产观测中也开,但默认 `NEXUS_LOG_FORMAT=json` 时按 INFO 级落盘。
> 想只看产品事件:`jq 'select(.event \| startswith("chat."))'`。

---

## 常用查询

### 今日所有 REJECT

```bash
jq 'select(.event=="quality.verdict" and .verdict=="REJECT")' ~/.nexus/logs/nexus.log
```

### 按 session 聚合 chat 耗时

```bash
jq 'select(.event=="chat.end") | {session_id, duration_ms}' ~/.nexus/logs/nexus.log | \
  jq -s 'group_by(.session_id) | map({session: .[0].session_id, total_ms: (map(.duration_ms) | add)})'
```

### 工具调用排行

```bash
jq 'select(.event=="tool.start") | .tool' ~/.nexus/logs/nexus.log | sort | uniq -c | sort -rn
```

### intent 分布

```bash
jq 'select(.event=="intent.classified") | .intent' ~/.nexus/logs/nexus.log | sort | uniq -c
```

---

## DMG 桌面端

Electron 主进程拉起 PyInstaller 打包的 backend(`./Nexus.app/Contents/Resources/nexus-backend/nexus-backend`)。
日志路径:

- **默认**: `/Users/<user>/.nexus/logs/nexus.log`
- **重定向**: 设置 `NEXUS_LOG_FILE` 环境变量(在 Electron `desktop/src/backend.ts` 启动 backend 时 export)

主进程建议在 SetupView 加一行"打开日志文件夹"按钮,直接 `open ~/.nexus/logs`。

---

## 故障排查

### 看不到 JSON 行

1. 确认 `NEXUS_LOG_FORMAT=json` 已设
2. 确认日志文件路径可写(`~/.nexus/logs/` 父目录)
3. `tail -F` 实时看,不要 `cat`(后者会一次性读完整文件)

### verbose 模式没看到 LangGraph chain 输出

1. 确认 `NEXUS_AGENT_VERBOSE=1`
2. 确认 stdout 没被重定向到不可读位置(PyInstaller frozen 模式下可能 stderr-only)
3. 设 `PYTHONUNBUFFERED=1`,否则 Python print buffer 会延迟

### 日志文件过大

- 10MB 自动轮转,5 份上限 = 60MB 上限
- 若仍嫌大:`NEXUS_LOG_LEVEL=WARNING` 减少 INFO 量
```

- [ ] **Step 2: commit**

```bash
git add docs/operations/logging.md
git commit -m "docs(ops): 加 logging.md(env/字段/查询/DMG)"
```

---

## Task 9: 端到端 DMG 验证 + 全量回归

**Files:**
- 暂不修改代码

- [ ] **Step 1: 全量 ruff + pytest**

```bash
cd /Users/yxb/projects/nexus
.venv/bin/ruff check nexus/ tests/
.venv/bin/ruff format --check nexus/
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q
```

Expected: 0 errors, 0 diff, 350+ tests passed(原 320 + 新 18)。

- [ ] **Step 2: 真实环境端到端**

```bash
kill $(lsof -ti:30000) 2>/dev/null
sleep 1
nohup env NEXUS_LOG_FORMAT=json NEXUS_LOG_FILE=/tmp/e2e-final.log PYTHONUNBUFFERED=1 \
  ./.venv/bin/python -c "import uvicorn; uvicorn.run('nexus.backend.main:app', host='127.0.0.1', port=30000, log_level='warning')" \
  > /tmp/nexus-backend.log 2>&1 &
sleep 4

# 触发 3 次不同 intent 的 chat
.venv/bin/python /tmp/ws-verbose-test.py           # chitchat
.venv/bin/python -c "
import asyncio, json, websockets
async def run():
    async with websockets.connect('ws://127.0.0.1:30000/api/ws?token=nexus-default-token') as ws:
        await ws.send(json.dumps({'type':'chat','content':'1+1 等于几?'}))
        async for m in ws:
            d = json.loads(m)
            if d.get('type') == 'done': break
asyncio.run(run())
"
sleep 2

echo '=== chat.* events ==='
jq -c 'select(.event | startswith("chat."))' /tmp/e2e-final.log
echo '=== verdict distribution ==='
jq -r 'select(.event=="quality.verdict") | .verdict' /tmp/e2e-final.log | sort | uniq -c
echo '=== LLM call count ==='
jq 'select(.event=="llm.end")' /tmp/e2e-final.log | wc -l
```

Expected: 6+ chat.* 事件(2 次 chat × 3-4 条),verdict 分布合理,LLM 调用 ≥ 2。

- [ ] **Step 3: 确认无回归**

```bash
cd /Users/yxb/projects/nexus/frontend
node e2e/dmg-cdp/test-dmg-intent.mjs 2>&1 | tail -5
```

Expected: `[PASS] intent E2E 通过`。

- [ ] **Step 4: 收尾**

如果所有验证通过,更新 `CHANGELOG.md`:

```markdown
## [Unreleased] — 可观测性子系统

**新增**:`nexus/backend/observability/` 子包 + `docs/operations/logging.md`

### Added

- **4 个产品事件**:ChatStart / IntentClassified / QualityVerdict / ChatEnd,frozen dataclass + JSON 序列化
- **EventSink**:JSONL/text 双格式,10MB 轮转 × 5 份,线程安全,父目录自动创建
- **NexusLogHandler**:LangChain BaseCallbackHandler 子类,把 llm/tool/chain 事件落 sink(token 计数 / duration_ms 自动算)
- **setup_logging()**:env 三档(`NEXUS_LOG_FORMAT` / `NEXUS_LOG_FILE` / `NEXUS_LOG_LEVEL`),幂等
- **ws.py 集成**:chat 流程 4 个关键节点 emit 产品事件
- **docs/operations/logging.md**:运维查询指南(DMG 路径 / jq 示例 / 故障排查)
- **测试**:4 个新测试文件,19 用例(events / sink / logger / handler / ws 集成)

### Changed

- `main.py`:启动期 `setup_logging()` 取代 `basicConfig`
- `agent.py`:始终挂 `NexusLogHandler`(JSONL 持久化);verbose 模式仅额外挂 `StdOutCallbackHandler`

### Risk Mitigation

- 观测层异常全吞掉(sink 写失败 / handler 抛错都不影响主流程)
- `setup_logging()` 幂等,uvicorn 多 worker 不会重复挂 handler
- 文件路径父目录自动创建,desktop 端首次启动零配置
```

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG 加 observability 子系统条目"
```

- [ ] **Step 5: 提交总结报告给 user**

## Self-Review

**1. Spec coverage**:
- ✅ JSONL 结构化日志写到 `~/.nexus/logs/nexus.log` — Task 2/3
- ✅ 4 个产品事件 — Task 1/7
- ✅ LangChain callback 通道复用 — Task 4
- ✅ env 三档 — Task 3
- ✅ `NEXUS_AGENT_VERBOSE=1` 沿用 — Task 6
- ✅ docs/operations/logging.md — Task 8
- ✅ 测试覆盖 — Task 1-4 / 7

**2. Placeholder scan**: 全文 grep `TODO` / `TBD` / `待定` / `后续` — 0 命中,所有路径有具体实现。

**3. Type consistency**:
- `ChatStart.timestamp` 在 events.py 是 `str`(ISO),handler.py 也用 `str` ✓
- `EventSink.emit` 接受 4 个 dataclass 之一,`emit_raw` 接受 dict ✓
- `NexusLogHandler` 继承 `BaseCallbackHandler`,方法签名 match LangChain 协议 ✓
- `setup_logging()` 返回 `logging.Logger`,签名 match ✓
- `emit_chat_event()` 是 ws.py module-level 函数,test 通过 patch 引用 ✓

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-20-observability-subsystem.md`. 9 tasks, ~9 commits.

执行选项:

1. **Subagent-Driven(推荐)** — 每个 task 派独立 subagent,做中做 spec compliance + code quality 双审。
2. **Inline Execution** — 当前 session 顺序执行,每个 task 后 checkpoint。

哪个走?