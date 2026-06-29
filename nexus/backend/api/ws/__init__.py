"""WebSocket 模块包:把 api/ws.py(1386 行)拆成职责单一的子模块。

模块布局:

- :mod:`.registry` — 客户端注册表(register / unregister / clients)
- :mod:`.auth` — REST 鉴权依赖(require_token)
- :mod:`.observability` — EventSink 单例 + emit helpers
- :mod:`.streaming` — 流式响应循环 + intent 分类 + token 估算 + 重试策略常量
- :mod:`.finalize` — 流结束收尾 + HITL 帧序列化 + resume 帧处理
- :mod:`.handlers` — WebSocket 主端点 ``handle_websocket``

WHY 拆分:旧 ``api/ws.py`` 单文件 1386 行超 python_project.md §1.2 上限
(单文件 ≤ 800 行)。拆分后每模块均 ≤ 500 行,职责清晰,后续单独修改某
一职责不会引发 merge 冲突。本包对外保持与旧文件完全一致的公共 API:

    from nexus.backend.api.ws import handle_websocket
    from nexus.backend.api.ws import require_token
    from nexus.backend.api.ws import WS_RETRY_POLICY
    from nexus.backend.api.ws import _ws_clients

兼容层 ``nexus/backend/api/ws.py`` 仍以模块形式存在(从本包 re-import),
无需修改 ``main.py`` 等导入方。
"""

from __future__ import annotations

# 重新导出所有公共符号,保持与旧 api/ws.py 一致的导入路径
from .auth import require_token
from .finalize import (
    _finalize_after_stream,
    _handle_resume_frame,
    _serialize_hitl_request,
)
from .handlers import handle_websocket
from .observability import (
    _emit_chat_end,
    _emit_quality_verdict,
    _get_observability_sink,
    emit_chat_event,
)
from .registry import (
    _clients_lock,
    _ws_clients,
    clients,
    register,
    unregister,
)
from .streaming import (
    _CLARIFY_TOOL_NAME,
    _EVT_CLARIFICATION_REQUEST,
    _EVT_CONFIRMATION_REQUEST,
    _EVT_CONFIRMATION_RESPONSE,
    _NON_RETRYABLE_ERROR_CODES,
    WS_RETRY_POLICY,
    _classify_and_record,
    _estimate_tokens,
    _is_retryable_error_code,
    _run_agent_streaming,
)

__all__ = [
    # 主端点
    "handle_websocket",
    # 鉴权
    "require_token",
    # 注册表
    "_ws_clients",
    "_clients_lock",
    "register",
    "unregister",
    "clients",
    # 流式 / 重试
    "WS_RETRY_POLICY",
    "_NON_RETRYABLE_ERROR_CODES",
    "_CLARIFY_TOOL_NAME",
    "_EVT_CLARIFICATION_REQUEST",
    "_EVT_CONFIRMATION_REQUEST",
    "_EVT_CONFIRMATION_RESPONSE",
    "_is_retryable_error_code",
    "_classify_and_record",
    "_estimate_tokens",
    "_run_agent_streaming",
    # finalize
    "_finalize_after_stream",
    "_serialize_hitl_request",
    "_handle_resume_frame",
    # 观测
    "_get_observability_sink",
    "emit_chat_event",
    "_emit_quality_verdict",
    "_emit_chat_end",
]
