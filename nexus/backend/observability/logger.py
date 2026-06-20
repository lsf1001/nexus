"""Nexus logging 配置入口。

env 三档:
  - ``NEXUS_LOG_FORMAT=text|json``(默认 text)
  - ``NEXUS_LOG_FILE=path``(默认 ``~/.nexus/logs/nexus.log``)
  - ``NEXUS_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR``(默认 INFO)

JSON 格式字段:``timestamp`` / ``level`` / ``name`` / ``message`` /
``module`` / ``lineno``。
text 格式:``2026-06-20 14:00:00 INFO test.logger hello world``(stdlib 默认)。

``setup_logging()`` 幂等:重复调用不会堆 handler。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

__all__ = ["setup_logging", "ENV_LOG_FORMAT", "ENV_LOG_LEVEL", "ENV_LOG_FILE"]


ENV_LOG_FORMAT: Final = "NEXUS_LOG_FORMAT"
ENV_LOG_LEVEL: Final = "NEXUS_LOG_LEVEL"
ENV_LOG_FILE: Final = "NEXUS_LOG_FILE"

_DEFAULT_LOG_LEVEL: Final = "INFO"
_VALID_FORMATS: Final = frozenset({"text", "json"})

_MARKER_ATTR: Final = "_nexus_observability_configured"
_HANDLER_OWNED_ATTR: Final = "_nexus_observability_owned"


class _JsonFormatter(logging.Formatter):
    """把 LogRecord 转成单行 JSON。不引第三方。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
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
    """配置根 logger。幂等。"""
    root = logging.getLogger()

    if getattr(root, _MARKER_ATTR, False):
        return root

    fmt = _resolve_format()
    level = _resolve_level()
    log_path = _resolve_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # 清理之前由本函数挂上的 handler,确保幂等
    for h in list(root.handlers):
        if getattr(h, _HANDLER_OWNED_ATTR, False):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001 — 关闭失败不阻断重新初始化
                pass

    setattr(handler, _HANDLER_OWNED_ATTR, True)
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, _MARKER_ATTR, True)

    logging.getLogger("deepagents").setLevel(logging.INFO)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langchain_core").setLevel(logging.WARNING)

    root.info("observability.setup_logging format=%s path=%s level=%s", fmt, log_path, level)
    return root
