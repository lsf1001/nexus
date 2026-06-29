"""观测层:EventSink 单例 + emit_chat_event + ChatEnd / QualityVerdict 序列化。

设计要点:
- EventSink 按 env ``NEXUS_LOG_FILE`` / ``NEXUS_LOG_FORMAT`` 重建(同 setup_logging)。
- 所有 emit 异常吞掉 — 观测层不能破坏主流程。
- 模块化拆分后,``api/ws/streaming.py`` 和 ``api/ws/finalize.py`` 都从这里 import
  :func:`emit_chat_event` / :func:`_emit_quality_verdict` / :func:`_emit_chat_end`。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...observability import ChatEnd, QualityVerdict
from ...observability.sink import EventSink

__all__ = [
    "emit_chat_event",
    "_emit_quality_verdict",
    "_emit_chat_end",
]


logger = logging.getLogger(__name__)

# 产品级观测事件 sink 单例:首次调用时按 env 重建,后续复用。
_observability_sink: EventSink | None = None


def _get_observability_sink() -> EventSink:
    """获取全局 EventSink 单例。

    首次调用时按 env 重建;后续复用。
    路径 / 格式遵循 :func:`nexus.backend.observability.logger.setup_logging`。
    """
    global _observability_sink
    if _observability_sink is None:
        _path = Path(os.environ.get("NEXUS_LOG_FILE", str(Path.home() / ".nexus" / "logs" / "nexus.log"))).expanduser()
        _fmt = os.environ.get("NEXUS_LOG_FORMAT", "text")
        _observability_sink = EventSink(path=_path, format=_fmt)
    return _observability_sink


def emit_chat_event(event: object) -> None:
    """公开 API:ws.py 各处 emit 产品事件。

    任何异常吞掉,观测层不能影响主流程。
    """
    try:
        _get_observability_sink().emit(event)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001 — 观测层异常不能影响主流程
        logger.warning("emit_chat_event 失败,已吞掉: %s", e)


def _emit_quality_verdict(final_response: Any, session_id: str, message_id: str) -> None:
    """把 FinalResponse 序列化成 QualityVerdict 事件并 emit。

    Score 是 :class:`~nexus.backend.rubrics.schemas.Score` dataclass,
    转成 ``{rubric_name: score}`` 字典便于 JSON 落盘。
    verdict 是 :class:`~nexus.backend.rubrics.schemas.RubricVerdict` 枚举,
    取 ``.value`` 拿到 "ACCEPT" / "REPAIR" / "REJECT" 字符串。
    """
    if final_response is None:
        return
    scores_dict: dict[str, float] = {}
    for s in getattr(final_response, "scores", ()) or ():
        name = getattr(s, "rubric_name", None)
        val = getattr(s, "score", None)
        if name and val is not None:
            scores_dict[str(name)] = float(val)
    verdict_obj = getattr(final_response, "verdict", None)
    verdict_str = getattr(verdict_obj, "value", str(verdict_obj) if verdict_obj else "")
    emit_chat_event(
        QualityVerdict(
            timestamp=datetime.now(tz=UTC).isoformat(),
            event="quality.verdict",
            session_id=session_id,
            message_id=message_id,
            verdict=verdict_str,
            scores=scores_dict,
            repair_attempted=bool(getattr(final_response, "repair_attempted", False)),
        )
    )


def _emit_chat_end(
    *,
    session_id: str,
    message_id: str,
    response_text: str,
    chat_start_monotonic: float,
    intent_result: Any,
    final_response: Any,
) -> None:
    """emit ChatEnd 事件:聚合本次 chat 的关键指标。

    字段映射:
      - chunks: 本次响应实际发送的 chunk 帧数。Task 2 之前按 16 字符分块,
        现在改为每个 token 1 个 chunk — 用 len(response_text) 近似(深
        度求精确值可由 _run_agent_streaming 透出计数,目前 ChatEnd 仅
        用于离线分析,粗估足够)。
      - duration_ms: 从 ChatStart 的 monotonic 起点到现在的差
      - retry_count / error_code: 来自 _run_agent_streaming 内部,
        handle_websocket 不可见,这里用 0 / None 占位
      - intent / verdict: 与前面 emit 的事件关联,便于聚合查询
    """
    chunks_count = len(response_text)
    duration_ms = int((time.monotonic() - chat_start_monotonic) * 1000)
    verdict_obj = getattr(final_response, "verdict", None) if final_response else None
    verdict_str = getattr(verdict_obj, "value", str(verdict_obj)) if verdict_obj else None
    emit_chat_event(
        ChatEnd(
            timestamp=datetime.now(tz=UTC).isoformat(),
            event="chat.end",
            session_id=session_id,
            message_id=message_id,
            chunks=chunks_count,
            duration_ms=duration_ms,
            retry_count=0,
            intent=intent_result,
            verdict=verdict_str,
            error_code=None,
        )
    )
