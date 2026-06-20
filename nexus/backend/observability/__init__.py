"""Nexus observability 子系统。

公开 API(逐步扩展,后续 Tasks 还会加 setup_logging / NexusLogHandler):
  - 事件 schema: :class:`ChatStart` / :class:`IntentClassified` /
    :class:`QualityVerdict` / :class:`ChatEnd`
  - 持久化 sink: :class:`EventSink`
"""

from __future__ import annotations

from .events import (
    EVENT_SCHEMA_VERSION,
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)
from .sink import EventSink

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "ChatEnd",
    "ChatStart",
    "EventSink",
    "IntentClassified",
    "QualityVerdict",
]
