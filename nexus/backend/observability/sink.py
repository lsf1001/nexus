"""EventSink:产品事件的持久化与展示通道。

设计要点:
  - **JSONL 文件**:每行一个事件,生产环境机器解析用。
  - **text 模式**:调试 / 桌面端 GUI 直接读用,kv 格式 `event=... session_id=...`。
  - **轮转**:`RotatingFileHandler`,10MB × 5 备份,默认。
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

    def _write(self, line: str) -> None:
        if self._closed:
            return
        with self._lock:
            handler = self._ensure_handler()
            handler.emit(
                logging.LogRecord(
                    name="nexus.observability",
                    level=logging.INFO,
                    pathname=__file__,
                    lineno=0,
                    msg=line,
                    args=(),
                    exc_info=None,
                )
            )

    def emit(self, event: ChatStart | IntentClassified | QualityVerdict | ChatEnd) -> None:
        """写入一个产品事件。线程安全。"""
        self._write(self._format_line(event.to_dict()))

    def emit_raw(self, payload: dict[str, Any]) -> None:
        """直接写一个 dict 事件(供 NexusLogHandler 等 LangChain callback 用)。"""
        self._write(self._format_line(payload))

    def _format_line(self, payload: dict[str, Any]) -> str:
        if self._format == "json":
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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
