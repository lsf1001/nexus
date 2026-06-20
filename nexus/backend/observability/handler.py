"""NexusLogHandler:把 LangChain 回调通道的事件落到 EventSink。

事件映射(start 带标识符 + 输入,end 带 duration + token 统计):
  - ``on_llm_start``   → ``{"event": "llm.start", "model": ..., "prompt_chars": N, "run_id": ...}``
  - ``on_llm_end``     → ``{"event": "llm.end", "run_id": ..., "duration_ms": N, "prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...}``
  - ``on_tool_start``  → ``{"event": "tool.start", "tool": name, "input_chars": N, "run_id": ...}``
  - ``on_tool_end``    → ``{"event": "tool.end", "run_id": ..., "duration_ms": N}``
  - ``on_chain_start`` → ``{"event": "chain.start", "chain": name, "run_id": ...}``
  - ``on_chain_end``   → ``{"event": "chain.end", "run_id": ..., "duration_ms": N}``

Sink 写入失败时吞掉异常(callback 链不能被观测层破坏)。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

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
        """构造 dict 并写 sink。任何异常吞掉。"""
        try:
            payload.setdefault("timestamp", datetime.now(tz=UTC).isoformat())
            payload.setdefault("event", "unknown")
            payload["run_id"] = payload.get("run_id") or self._run_id
            self._sink.emit_raw(payload)
        except Exception:  # noqa: BLE001 - 观测层不能破坏 callback 链
            _logger.exception("NexusLogHandler 写 sink 失败,已吞掉")

    # ----- LangChain 回调 -----

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        self._start_times[run_id] = time.monotonic()
        self._emit(
            {
                "event": "llm.start",
                "model": serialized.get("name", "unknown"),
                "prompt_chars": sum(len(p) for p in prompts),
                "run_id": run_id,
            }
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        usage = getattr(response, "llm_output", None) or {}
        token_usage = usage.get("token_usage", {}) if isinstance(usage, dict) else {}
        self._emit(
            {
                "event": "llm.end",
                "run_id": run_id,
                "duration_ms": duration_ms,
                "prompt_tokens": token_usage.get("prompt_tokens"),
                "completion_tokens": token_usage.get("completion_tokens"),
                "total_tokens": token_usage.get("total_tokens"),
            }
        )

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        self._start_times[run_id] = time.monotonic()
        self._emit(
            {
                "event": "tool.start",
                "tool": serialized.get("name", "unknown"),
                "input_chars": len(input_str),
                "run_id": run_id,
            }
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        self._emit(
            {
                "event": "tool.end",
                "run_id": run_id,
                "duration_ms": duration_ms,
            }
        )

    def on_chain_start(self, serialized: dict[str, Any], inputs: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        self._start_times[run_id] = time.monotonic()
        self._emit(
            {
                "event": "chain.start",
                "chain": serialized.get("name") if serialized else None,
                "run_id": run_id,
            }
        )

    def on_chain_end(self, outputs: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        start = self._start_times.pop(run_id, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        self._emit(
            {
                "event": "chain.end",
                "run_id": run_id,
                "duration_ms": duration_ms,
            }
        )
