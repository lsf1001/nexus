"""Nexus observability 子系统。

公开 API:
  - 事件 schema: :class:`ChatStart` / :class:`IntentClassified` /
    :class:`QualityVerdict` / :class:`ChatEnd`
  - 持久化 sink: :class:`EventSink`
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
from .sink import EventSink

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "ChatEnd",
    "ChatStart",
    "EventSink",
    "IntentClassified",
    "NexusLogHandler",
    "QualityVerdict",
    "setup_logging",
]
