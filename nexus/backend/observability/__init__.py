"""Nexus observability 子系统。

公开 API(逐步扩展,Tasks 2/3/4 还会加 EventSink / setup_logging / NexusLogHandler):
  - 事件 schema: :class:`ChatStart` / :class:`IntentClassified` /
    :class:`QualityVerdict` / :class:`ChatEnd`
"""

from __future__ import annotations

from .events import (
    EVENT_SCHEMA_VERSION,
    ChatEnd,
    ChatStart,
    IntentClassified,
    QualityVerdict,
)

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "ChatEnd",
    "ChatStart",
    "IntentClassified",
    "QualityVerdict",
]
