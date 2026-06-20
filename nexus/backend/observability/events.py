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
