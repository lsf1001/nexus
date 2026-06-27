"""WebSocket 端点及流式响应相关的实现。

本模块独立承载：
  - WS 客户端注册表（``_ws_clients`` / ``_clients_lock``），供微信等外部通道
    在主事件循环中广播消息。
  - Agent 流式响应循环（``_run_agent_streaming``）：把
    :class:`~nexus.backend.resilience.stream_guard.StreamGuard` 的事件转成
    WS 帧（``token_usage`` / ``thinking`` / ``chunk`` / ``final`` / ``stats`` /
    ``done`` / ``error``）。
  - 断点续传帧处理（``_handle_resume_frame``）。
  - 主端点 ``handle_websocket``：由 ``main.py`` 通过
    :meth:`fastapi.FastAPI.websocket` 装饰器注册到路由表上。
  - REST 共享鉴权依赖 ``require_token``（与 WebSocket 复用的 token 校验）。

设计约束：
  - 本模块**不**反向 import ``main.py``，避免循环依赖。
  - 业务依赖（当前 Agent 实例、微信回调）通过参数注入到 ``handle_websocket``。
  - REST 路由（``/api/context``、``/api/model``、``/api/channels`` 等）继续留在
    ``main.py``，本任务范围只拆 WebSocket 部分。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect

from ..config import CONFIG
from ..db import add_message
from ..intent.router import (
    DEFAULT_INTENT,
    IntentKind,
    classify_intent,
)
from ..llm.policies import RetryPolicy
from ..observability import ChatEnd, ChatStart, IntentClassified, QualityVerdict
from ..observability.sink import EventSink
from ..resilience.resume import (
    InvalidResumeToken,
    make_token,
    verify_token,
)
from ..resilience.stream_guard import StreamGuard

logger = logging.getLogger(__name__)

# WS 流式响应的默认重试策略（基延迟 0.1s，上限 2s，±20% 抖动）
WS_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay=0.1, max_delay=2.0, jitter=0.2)

# 产品级观测事件 sink 单例:首次调用时按 env 重建,后续复用。
# 重建路径与 setup_logging 一致:env NEXUS_LOG_FILE / NEXUS_LOG_FORMAT 决定落盘位置与格式。
_observability_sink: EventSink | None = None


def _get_observability_sink() -> EventSink:
    """获取全局 EventSink 单例。

    首次调用时按 env 重建;后续复用。
    路径 / 格式遵循 :func:`nexus.backend.observability.logger.setup_logging`。
    """
    global _observability_sink
    if _observability_sink is None:
        import os as _os
        from pathlib import Path as _Path

        _path = _Path(
            _os.environ.get("NEXUS_LOG_FILE", str(_Path.home() / ".nexus" / "logs" / "nexus.log"))
        ).expanduser()
        _fmt = _os.environ.get("NEXUS_LOG_FORMAT", "text")
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


# _run_agent_streaming 内部 16 字符分块大小(与 ws.py line 390 一致),用于
# ChatEnd 的 chunks 字段估算。
_STREAM_CHUNK_SIZE = 16


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
      - chunks: response_text 长度按 16 字符分块数
      - duration_ms: 从 ChatStart 的 monotonic 起点到现在的差
      - retry_count / error_code: 来自 _run_agent_streaming 内部,
        handle_websocket 不可见,这里用 0 / None 占位
        (后续如需精确值,可扩展 _run_agent_streaming 返回值)
      - intent / verdict: 与前面 emit 的事件关联,便于聚合查询
    """
    chunks_count = (len(response_text) + _STREAM_CHUNK_SIZE - 1) // _STREAM_CHUNK_SIZE
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


async def _finalize_after_stream(
    *,
    websocket: WebSocket,
    session_id: str,
    user_content: str,
    message_id: str,
    chat_start_monotonic: float,
    intent_result: Any,
    last_event_id: int,
    response_text: str,
    stream_completed: bool,
    clarification: tuple[str, list[str]] | None,
    pending_interrupts: tuple | None,
    agent: Any,
    get_quality_pipeline: Callable[[], Any] | None,
) -> None:
    """流结束后的统一收尾：澄清挂起 / HITL 挂起 / 质量门 / 入库 / done / emit ChatEnd。

    适用于:
      - 普通 user 消息路径(``_run_agent_streaming`` 之后)
      - ``confirmation_response`` 续流路径(二次 ``_run_agent_streaming`` 之后)

    WHY:Task 4 commit ``ca6dec5`` 之后,``confirmation_response`` 分支注释
    说 "fall through 到质量门 / 入库 / done",但实际不会 —— 该帧的
    ``content`` 字段是空,被 user 消息路径的 ``if not user_content: continue``
    拦截,导致 approve 后 LLM 续流响应既不入库也不发 done。本 helper 把两
    条路径的 finalize 合并,消除路径分叉。

    Args:
        websocket: 目标 ws。
        session_id: 会话 id。
        user_content: 本轮 user 消息原文。普通 user 消息路径用真实文本;
            ``confirmation_response`` 续流场景是空串,pipeline 内部应兜底。
        message_id: 本轮统一 id,用于入库 + ChatEnd 关联。
        chat_start_monotonic: ChatStart 的 monotonic 起点(普通 user 消息
            路径在收到消息时记,confirmation_response 续流场景重新计时)。
        intent_result: 意图分类结果。普通 user 消息场景由
            ``_classify_and_record`` 给出;confirmation_response 续流场景
            用 ``DEFAULT_INTENT`` 兜底(没有 intent 分类)。
        last_event_id: 来自 ``_run_agent_streaming``。
        response_text: 来自 ``_run_agent_streaming``。
        stream_completed: 来自 ``_run_agent_streaming``。
        clarification: 来自 ``_run_agent_streaming``;非空时不跑后续质量门 /
            入库 / done(挂起状态需要等下次输入),改为入库 placeholder。
        pending_interrupts: 来自 ``_run_agent_streaming``;非空时直接
            early-return(HITL 挂起,等下次 ``confirmation_response``)。
        agent: 用于 ChatEnd 观测。
        get_quality_pipeline: 可选 callable,用于质量门。``None`` 或返回
            ``None`` 时跳过质量门(向后兼容)。
    """
    # 澄清挂起：把 ask_user 调用 + 问题追加到会话历史(作为 assistant 角色),
    # 用户下一条消息进来时 LLM 能自然接住。不发 done。
    if clarification is not None:
        clarify_question, _clarify_options = clarification
        placeholder = f"[澄清中] {clarify_question}"
        # 占位消息是"会话回放时让用户看到 AI 刚才问了 X"的可选辅助,
        # 写失败(典型:deepagents aiosqlite 后台持 WAL 锁 > busy_timeout)
        # 不应让 ws 主循环崩 —— clarify_request 帧已经发出去了,
        # 前端已经显示澄清表单,业务侧已经在等用户回答。OperationalError
        # 降级为 warning log,不影响协议层。
        try:
            add_message(str(uuid.uuid4()), session_id, "assistant", placeholder)
        except Exception as persist_exc:  # noqa: BLE001 — 持久化失败不影响协议
            logger.warning(
                "WS 澄清占位消息入库失败,降级跳过 (session=%s, exc=%s)",
                session_id,
                persist_exc,
            )
        return

    # HITL 挂起：``_run_agent_streaming`` 已经发了 ``confirmation_request`` +
    # 写入 ``_session_hitl_state``,这里什么都不做(等 ``confirmation_response``)。
    if pending_interrupts is not None:
        return

    # 质量门(同 user 消息路径原逻辑)
    pipeline = get_quality_pipeline() if get_quality_pipeline else None
    final_response: Any = None
    if pipeline is not None and response_text:
        try:
            pipeline.set_session_id(session_id)
            final_response = await pipeline.run_with_quality(
                question=user_content,
                raw_response=response_text,
                message_id=message_id,
            )
            # 不补发 final 帧 —— agent 流式结束时已经在 ``_run_agent_streaming``
            # 里发过一个 ``final: 长回复`` 帧给客户端,质量门 verdict 只影响
            # 入库文本,不影响用户视图(详见原 handle_websocket 实现注释)。
            _emit_quality_verdict(final_response, session_id, message_id)
        except Exception as exc:  # noqa: BLE001 — 质量门异常不污染主流程
            logger.warning("QualityPipeline 失败，使用原回复: %s", exc)

    # 签发新 resume token 给客户端(仅在配置了 secret 且会话建立后)
    if session_id and last_event_id > 0:
        try:
            new_token = make_token(session_id, last_event_id)
        except RuntimeError:
            # CONFIG 中 resume_secret 和 ws_token 都为空 → 静默不签发
            new_token = None
        if new_token:
            await websocket.send_json(
                {
                    "type": "resume_token",
                    "resume_token": new_token,
                    "last_event_id": last_event_id,
                }
            )

    # 保存助手回复到数据库
    if response_text:
        add_message(message_id, session_id, "assistant", response_text)

    # 发 done + emit ChatEnd
    if stream_completed:
        done_event_id = last_event_id + 1
        await websocket.send_json(
            {
                "type": "done",
                "content": "",
                "event_id": done_event_id,
            }
        )
        _emit_chat_end(
            session_id=session_id,
            message_id=message_id,
            response_text=response_text,
            chat_start_monotonic=chat_start_monotonic,
            intent_result=intent_result,
            final_response=final_response,
        )


# 当前已注册的 WebSocket 客户端列表（供微信等外部通道在主循环中广播）
_ws_clients: list[WebSocket] = []
_clients_lock = threading.RLock()


# 不可重试的错误码集合（与 StreamGuard 的 _map_error_code 输出对齐）
_NON_RETRYABLE_ERROR_CODES = frozenset({"auth", "bad_request", "context_length", "content_filter"})

# 澄清工具名（与 nexus.backend.tools.ask_user.name 对齐）
_CLARIFY_TOOL_NAME = "ask_user"
# WS 帧类型常量
_EVT_CLARIFICATION_REQUEST = "clarification_request"
_EVT_CONFIRMATION_REQUEST = "confirmation_request"
_EVT_CONFIRMATION_RESPONSE = "confirmation_response"
# _run_agent_streaming 返回值新增第四个:clarification_question(str|None)、
# clarification_options(list[str]|None),供 handle_websocket 判断是否被澄清挂起。

# HITL 挂起状态读取:langgraph 0.6+ 把 interrupt 信息存到 checkpoint 的
# ``__interrupt__`` channel,直接 ``await agent.aget_state(thread_id)`` 拿回
# Interrupt 列表,不用进程内缓存(多 worker 部署天然兼容)。


def _serialize_hitl_request(
    hitl_request: Any,
    *,
    interrupt_id: str,
    event_id: int,
) -> dict[str, Any]:
    """把 langchain HITL 标准 hitl_request payload 转 WS confirmation_request 帧。

    hitl_request 标准格式(由 langchain ``HumanInTheLoopMiddleware`` 生成)::

        {
            "action_requests": [
                {"name": "write_file", "args": {...}, "description": "..."},
                ...
            ],
            "review_configs": {...},
        }

    转换:每个 ``action_request`` 展开成一个 ``actions`` 项,含工具名 +
    目标路径 + 200 字截断内容预览 + approve / reject 两个决策选项。

    WHY 必须手动展开:langchain 给的是"通用协议"dict,前端不便直接消费;
    本函数把"工具调用入参"翻译成"用户友好视图"(路径 / 预览 / 决策按钮)。

    Args:
        hitl_request: langchain HumanInTheLoopMiddleware 抛出的
            ``Interrupt.value``。容错处理:既接受 dict,也接受其它类型
            (str / None)——异常时仍返回完整帧结构,只是 actions 为空。
        interrupt_id: langgraph ``Interrupt.id``,续流时用。
        event_id: 本次流的递增 event_id。

    Returns:
        ``confirmation_request`` 帧 dict,可直接 ``websocket.send_json()``。
    """
    actions: list[dict[str, Any]] = []
    if isinstance(hitl_request, dict):
        for req in hitl_request.get("action_requests", []) or []:
            if not isinstance(req, dict):
                continue
            name = str(req.get("name", "unknown"))
            args = req.get("args") or {}
            # 目标路径:write_file/edit_file 用 file_path,ls/glob/grep 用 path
            target_path = args.get("file_path") or args.get("path") or "(未知路径)"
            # 内容预览:write_file 用 content,edit_file 用 new_string
            content = args.get("content") or args.get("new_string") or ""
            content_str = str(content)
            preview = (content_str[:200] + "...") if len(content_str) > 200 else content_str
            actions.append(
                {
                    "tool_name": name,
                    "target_path": str(target_path),
                    "preview": preview,
                    "description": str(req.get("description", "")),
                    "options": [
                        {"label": "批准", "decision": "approve"},
                        {"label": "拒绝", "decision": "reject"},
                    ],
                }
            )
    return {
        "type": _EVT_CONFIRMATION_REQUEST,
        "event_id": event_id,
        "interrupt_id": interrupt_id,
        "actions": actions,
    }


def _estimate_tokens(
    content: str | list,
    context_window: int = 200000,
) -> tuple[int, int]:
    """估算 token 数量和上下文使用率。

    委托给 :func:`langchain_core.messages.utils.count_tokens_approximately` —
    与 deepagents 内部 ``_should_summarize`` 用**同一套** token 估算。
    这样 UI 显示的"上下文用量 %"和"自动压缩触发阈值"在**同一基准**上,
    不会出现 UI 说 89% 但实际才 8% 那种"误以为快压缩了"的错位。

    WHY 不再用字符系数(中 2.5 / 英 0.25 / 其他 0.5):
      实测 71200 中文字符:旧系数 = 178k tokens(89%),新计数 = ~18k(9%),差 10×。
      字符系数高估,误导用户以为快触顶了。改用 langchain 启发式更接近 deepagents
      实际决策。

    Args:
        content: 估算对象,两种形式:
            - ``str``: 单段文本(测试/降级用,内部包成 HumanMessage)
            - ``list``: 整个会话的 messages(BaseMessage 或 ``{"role":..., "content":...}``
              dict 都可)。**生产场景必传 list**,让 UI 显示的是"整个对话
              占比",不是"本轮响应占比"。
        context_window: 上下文窗口 token 数。默认 200000,
            匹配 :envvar:`NEXUS_CONTEXT_WINDOW` 默认值。

    Returns:
        ``(token_count, context_usage_percent)``:
          - ``token_count``:估算的 token 数(可能含 per-message overhead,
            ``count_tokens_approximately`` 的语义)
          - ``context_usage_percent``:相对 ``context_window`` 的占用百分比
            (0.0-100.0,保留 1 位小数,clamp 到 100)
    """
    # 局部 import:启动时少一个顶层依赖;且 count_tokens_approximately 在 ws
    # 端点热路径,延迟到调用时再 resolve,符合 Pylance 的"用时导入"建议。
    from langchain_core.messages.utils import count_tokens_approximately

    # 空内容短路:count_tokens_approximately 对空 HumanMessage 仍返回 ~4
    # tokens(per-message overhead),但语义上空内容应 0 token。否则前端
    # "用了 0.0%" 在用户没说话时会被显示成"用了 0.002%",误导。
    if isinstance(content, str):
        if not content:
            return 0, 0.0
        from langchain_core.messages import HumanMessage

        token_count = count_tokens_approximately([HumanMessage(content=content)])
    else:
        if not content:
            return 0, 0.0
        token_count = count_tokens_approximately(content)

    if context_window <= 0:
        context_window = 200000
    context_usage = round(token_count / context_window * 100, 1)
    return token_count, min(context_usage, 100.0)


def _extract_request_token(request: Request) -> str:
    """从 header / query 提取 token；REST 鉴权用。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token", "")


def require_token(request: Request) -> None:
    """FastAPI 依赖：校验 REST 请求 token。失败抛 401。"""
    token = _extract_request_token(request)
    expected = CONFIG.get("ws_token", "")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="未授权")


def _is_retryable_error_code(error_code: str) -> bool:
    """根据 wire 上的 ``error_code`` 判断是否还可重试。

    - ``*_exhausted`` 后缀表示重试已用尽 → 不可重试
    - ``auth`` / ``bad_request`` / ``context_length`` / ``content_filter`` 这类
      结构性错误即使没加 exhausted 后缀也不应再重试
    - 其余（``rate_limit`` / ``timeout`` / ``unknown``）视为可重试

    Args:
        error_code: 来自 StreamGuard 错误事件的 ``error_code`` 字段。

    Returns:
        是否还可重试。
    """
    if error_code.endswith("_exhausted"):
        return False
    return error_code not in _NON_RETRYABLE_ERROR_CODES


async def _classify_and_record(
    get_intent_llm: Callable[[], Any] | None,
    session_id: str,
    user_content: str,
) -> IntentKind:
    """调主 LLM 分类 + 把 user 消息(含 intent)写库。

    任何异常 / llm=None 一律兜底 chitchat(最安全:不影响 task 工具链)。
    """
    intent: IntentKind = DEFAULT_INTENT
    llm: Any = None
    if get_intent_llm is not None:
        try:
            llm = get_intent_llm()
        except Exception:  # noqa: BLE001
            llm = None
    if llm is not None:
        intent = await classify_intent(llm, user_content)
    # 入库(用 generate uuid;不传 thinking_content,跟 add_message 默认对齐)
    add_message(str(uuid.uuid4()), session_id, "user", user_content, intent=intent)
    return intent


async def _run_agent_streaming(
    websocket: WebSocket,
    session_id: str,
    prompt: dict,
    agent: Any,
    resume_from_event_id: int | None = None,
    *,
    command_resume: dict[str, Any] | None = None,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None]:
    """运行 agent 流式响应，把事件转发到 WebSocket。

    使用 :class:`StreamGuard` 包装 ``agent.astream_events``：
      - 给每个事件附加进程内单调递增的 ``event_id``
      - 可重试错误自动重试；不可重试 / 重试用尽 → yield 1 个 error 事件
      - 永不抛异常（StreamGuard 已保证），调用方不需要再 try/except
      - 检测到 LLM 调用 ``ask_user`` 工具时,发送 ``clarification_request``
        帧并挂起(不再发 final / done),用户回答通过新 turn 注入历史。
      - 检测到 ``GraphInterrupt``(langchain HITL 中断)时,发 ``confirmation_request``
        帧 + 把 ``pending_interrupts`` 填入返回值第 5 元组,handle_websocket 据此
        挂起本轮流,等客户端发 ``confirmation_response`` 后用 ``Command(resume=...)``
        新 astream 续流。

    Args:
        websocket: 目标 WebSocket 连接。
        session_id: 会话 ID（用于日志上下文 / HITL thread_id）。
        prompt: 已构建好的 prompt dict（含 ``messages``）。
        agent: 当前 Agent 实例（由 ``main.py`` 在调用时通过 ``get_agent()`` 注入）。
        resume_from_event_id: 客户端断点续传位置；Phase 1 简化模型下
            仅作为"客户端告知 server 上次看到哪"，不做真正的去重过滤
            （每次流都有新的 event_id 序列）。
        command_resume: HITL 续流 payload(``{"decisions": [...]}``)。非空时
            跳过 messages 输入,改用 ``Command(resume=command_resume)`` 续流
            已挂起的图。

    Returns:
        ``(last_event_id, response_text, completed, clarification, pending_interrupts)``：
          - ``last_event_id`` 本次流结束时的最后一个 event_id（供下次签发 resume token）。
          - ``response_text`` 剥离 ``<thinking>`` 标签后的纯回复文本（用于 DB 存储）。
            错误 / HITL 挂起 路径返回空字符串。
          - ``completed`` 表示本次流是否正常完成；错误 / 澄清 / HITL 挂起路径不应再发 ``done``。
          - ``clarification`` ``(question, options)`` 当 LLM 调用 ``ask_user``
            时填入,handle_websocket 据此跳过质量门 + 跳过 ``done`` 帧。
          - ``pending_interrupts`` ``tuple[Interrupt, ...] | None`` 当 HITL 触发时填入,
            handle_websocket 据此挂起本轮流,等客户端发 confirmation_response 后用
            ``Command(resume=...)`` 新 astream 继续。
    """
    if agent is None:
        # 没可用 agent（极端情况：启动时没模型 key）
        await websocket.send_json(
            {
                "type": "error",
                "content": "agent 未初始化",
                "error_code": "agent_unavailable",
                "retryable": False,
                "event_id": 1,
            }
        )
        return 1, "", False, None, None

    # StreamGuard 包 astream_events；每次重试会重新调一次 astream_events
    # （幂等重试，由上游 LLM 自行决定是否真幂等）。
    # 挂 NexusLogHandler(必挂,生产 JSONL 落盘) + StdOutCallbackHandler(仅 verbose 模式)
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

    # checkpointer 必须配 thread_id 才能让 Command(resume=...) 找回挂起状态。
    # session_id 单进程内唯一,直接当 thread_id。
    existing_config = astream_kwargs.get("config") or {}
    astream_kwargs["config"] = {
        **existing_config,
        "configurable": {
            **dict(existing_config.get("configurable") or {}),
            "thread_id": session_id,
        },
    }

    # astream 输入:HITL 续流用 Command(resume=...),正常 turn 用 messages dict。
    # langgraph astream_events overload 接受 Command 作为 input(
    # langgraph/pregel/main.py:3691),从 checkpointer 找回挂起的图状态。
    if command_resume is not None:
        from langgraph.types import Command

        astream_input: Any = Command(resume=command_resume)
    else:
        astream_input = {"messages": prompt["messages"]}

    # 关键:把 GraphInterrupt 透传出来。StreamGuard 默认 ``except Exception``
    # 会把 GraphInterrupt 当 classified 错误吞掉,yield 一个 error 事件——
    # 但 HITL 不是错误,它是 langgraph 设计的"图挂起"机制(继承 GraphBubbleUp)。
    #
    # 实现要点:``agent.astream_events`` 内部抛 GraphInterrupt 是发生在
    # async generator 的 ``__anext__`` 阶段,不在工厂调用瞬间。所以工厂必须
    # 自己消费 generator 并在内部 ``async for`` 处 try/except,再 raise 出来
    # —— 这样 StreamGuard 的 ``async for event in _call_factory(...)`` 就会
    # 捕获到 GraphInterrupt,从外层 try/except 透传到 _run_agent_streaming。
    async def _astream_factory(input_: Any, **kw: Any) -> Any:
        agen = agent.astream_events(input_, **kw)
        try:
            async for event in agen:
                yield event
        except GraphInterrupt:
            raise

    guard = StreamGuard(
        astream_events=_astream_factory,
        retry_policy=WS_RETRY_POLICY,
        max_total_retries=2,
    )

    last_event_id = 0
    full_response = ""
    had_error = False

    # v1 is deprecated since langchain-core 1.0; v2 keeps the same event
    # names (on_chat_model_stream / on_tool_start / on_tool_end) and the
    # same data shape (data.chunk / data.output), so the rest of the loop
    # works unchanged.
    astream_kwargs_with_version = {**astream_kwargs, "version": "v2"}

    # HITL 处理:HITL 抛 GraphInterrupt(继承 GraphBubbleUp)是 langgraph
    # 的"图挂起"协议,不是 LLM 错误。在 StreamGuard 外层捕获后翻译成
    # confirmation_request 帧,不要让 StreamGuard 把它当 unknown error 吞。
    from langgraph.errors import GraphInterrupt

    try:
        async for event in guard.astream_events(astream_input, **astream_kwargs_with_version):
            event_id = int(event.get("event_id", 0))
            event_type = event.get("event")

            # StreamGuard 错误事件
            if event.get("type") == "error":
                error_code = event.get("error_code", "unknown")
                retryable = _is_retryable_error_code(error_code)
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": event.get("message", "未知错误"),
                        "event_id": event_id,
                        "error_code": error_code,
                        "retryable": retryable,
                    }
                )
                last_event_id = event_id
                had_error = True
                # 不可重试 / 已耗尽：停止流（不再发 done）。
                # 返回空字符串，避免在错误路径下把 raw 文本（含 thinking 标签）写入 DB。
                if not retryable:
                    return last_event_id, "", False, None, None
                # 可重试但 StreamGuard 仍 yield error，意味着情况特殊
                # （理论上不会到这里，StreamGuard 内部就用尽了）。安全起见停止。
                return last_event_id, "", False, None, None

            # Phase 1 resume 过滤：跳过 event_id <= resume_from_event_id 的事件
            if resume_from_event_id is not None and event_id > 0 and event_id <= resume_from_event_id:
                last_event_id = max(last_event_id, event_id)
                continue

            # 业务事件转发
            if event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                content = getattr(chunk, "content", "") if chunk else ""
                if content:
                    # 仅累积，不在流中转发 chunk；后处理阶段会按 16 字符分块发出去
                    full_response += content
            elif event_type == "on_chat_model_end":
                # 非流式 LLM(mock / 老式客户端)只发 end 不发 stream —
                # 此时 on_chat_model_stream 整个流里没有累积,需要从 end 拿全量
                # content 兜底,否则 reject 反思 / mock LLM 这类"一次性返回"的
                # 场景 full_response 始终为空,前端收不到任何 chunk/final。
                output = event.get("data", {}).get("output")
                end_content = getattr(output, "content", "") if output else ""
                if isinstance(end_content, str) and end_content and not full_response:
                    full_response = end_content
            elif event_type == "on_tool_start":
                tool_name = event.get("name", "未知工具")
                tool_input = event.get("data", {}).get("input") or {}
                logger.info(
                    "WS on_tool_start: session=%s tool=%s event_id=%s input=%s",
                    session_id,
                    tool_name,
                    event_id,
                    str(tool_input)[:200],
                )
                if tool_name == _CLARIFY_TOOL_NAME:
                    # === 澄清挂起 ===
                    # LLM 决定追问用户:把工具入参(问题 + 候选项)作为
                    # clarification_request 帧发出,然后**挂起本轮流**——
                    # 不发 final / done,让客户端在 UI 弹表单。
                    # 用户回答通过新 turn 的用户消息注入,LLM 看到 ask_user 调
                    # 用历史 + 用户回答,继续原任务。
                    tool_input = event.get("data", {}).get("input") or {}
                    question = str(tool_input.get("question", "")).strip()
                    raw_options = tool_input.get("options") or []
                    options: list[str] = []
                    if isinstance(raw_options, list):
                        # LLM 既可能传 ["火锅","烧烤"] 纯字符串列表,
                        # 也可能传 [{key:"classic",label:"经典必玩",description:"..."}]
                        # 字典列表(更丰富)。前端只展示纯文本按钮,所以这里
                        # 把字典规范化为 label 字符串 — 优先 label/content/text/
                        # value/name(覆盖各家 LLM 命名习惯;content 是 MiniMax
                        # 默认风格,label 是 OpenAI/Anthropic 风格),都缺再 str()
                        # 兜底。空字符串 / 纯空白丢弃。
                        for opt in raw_options:
                            label: str | None = None
                            if isinstance(opt, str):
                                label = opt if opt.strip() else None
                            elif isinstance(opt, dict):
                                # 优先 label/content/text/value/name 字段
                                for key in ("label", "content", "text", "value", "name"):
                                    v = opt.get(key)
                                    if isinstance(v, str) and v.strip():
                                        label = v
                                        break
                                # 都没匹配 → 退化到 key 字段(MiniMax 习惯用
                                # {key: "本周末", description: "..."})
                                if label is None:
                                    key_field = opt.get("key")
                                    if isinstance(key_field, str) and key_field.strip():
                                        label = key_field
                                # 仍没找到可读字段 → 跳过(避免把 "{'label': ''}"
                                # 这种噪音字典转字符串塞给用户,宁可让前端走自由输入)
                            # None / 空字符串 / 字典无有效字段 → 不追加
                            if label is None:
                                continue
                            options.append(label.strip())
                            if len(options) >= 6:
                                break

                    if not question:
                        # 工具入参异常 —— 走默认分支,继续按普通工具处理
                        logger.warning("ask_user 工具入参缺少 question,降级为普通工具调用")
                        await websocket.send_json(
                            {
                                "type": "thinking",
                                "content": f"[调用工具] {tool_name}",
                                "event_id": event_id,
                            }
                        )
                    else:
                        if event_id > last_event_id:
                            last_event_id = event_id
                        await websocket.send_json(
                            {
                                "type": _EVT_CLARIFICATION_REQUEST,
                                "content": question,
                                "options": options,
                                "event_id": last_event_id,
                            }
                        )
                        logger.info(
                            "WS clarification_request 发送: session=%s, q=%s, options=%d",
                            session_id,
                            question[:60],
                            len(options),
                        )
                        return last_event_id, "", False, (question, options), None
                else:
                    await websocket.send_json(
                        {
                            "type": "thinking",
                            "content": f"[调用工具] {tool_name}",
                            "event_id": event_id,
                        }
                    )
            elif event_type == "on_tool_end":
                tool_name = event.get("name", "未知工具")
                output = event.get("data", {}).get("output")
                logger.info(
                    "WS on_tool_end: session=%s tool=%s event_id=%s output_chars=%d",
                    session_id,
                    tool_name,
                    event_id,
                    len(str(output)) if output else 0,
                )
                await websocket.send_json(
                    {
                        "type": "thinking",
                        "content": f"[工具返回] {str(output)[:100]}..." if output else "",
                        "event_id": event_id,
                    }
                )
            # 其它事件（chain start/end、retriever、agent 节点等）→ 忽略，仅跟踪 event_id

            if event_id > last_event_id:
                last_event_id = event_id
    except GraphInterrupt as gi:
        # HITL 中断(理论路径,langgraph 0.6+ 实际会在 _loop.__exit__ 中主动 suppress,
        # 见下方 ``agent.get_state(...).interrupts`` fallback):把 langgraph Interrupt
        # 序列翻成 confirmation_request 帧,pending 状态存入 _session_hitl_state 供
        # confirmation_response 续流。
        interrupts = gi.args[0] or ()  # GraphInterrupt(interrupts=[...])
        logger.info(
            "WS HITL GraphInterrupt 捕获: session=%s, interrupts=%d",
            session_id,
            len(interrupts),
        )
        for intr in interrupts:
            last_event_id += 1
            frame = _serialize_hitl_request(intr.value, interrupt_id=str(intr.id), event_id=last_event_id)
            await websocket.send_json(frame)
            first_action = frame["actions"][0] if frame["actions"] else {}
            logger.info(
                "WS confirmation_request 发送: session=%s, tool=%s, target=%s",
                session_id,
                first_action.get("tool_name", "?"),
                first_action.get("target_path", "?"),
            )
        pending: tuple | None = tuple(interrupts) if interrupts else None
        # WHY 不写 _session_hitl_state:挂起 interrupt 已经存到 checkpoint 的
        # ``__interrupt__`` channel,续流时通过 ``agent.aget_state(thread_id)``
        # 读回,无需进程内缓存(多 worker 部署天然兼容)。
        return last_event_id, "", False, None, pending

    # langgraph 0.6+ 关键修正:Pregel._loop.__exit__ 会主动 ``return True`` 抑制
    # GraphInterrupt(把 interrupt 信息存到 checkpoint 的 ``__interrupt__`` channel),
    # 所以 ``agent.astream_events`` 不抛异常而正常结束。HITL 状态只能从
    # ``agent.get_state(config).interrupts`` 读取 — 这是 langgraph 0.6+ 暴露
    # pending interrupt 的官方 API。
    try:
        # WHY ``agent.aget_state``(不是 ``get_state``):agent 用 AsyncSqliteSaver
        # 时,``checkpointer.aget_tuple`` 是 async;同步 ``get_state`` 内部
        # ``checkpointer.get_tuple(config)`` 在 AsyncSqliteSaver 上拿到的是
        # coroutine(没 await),触发 "coroutine 'aget_tuple' was never awaited"
        # warning,interrupts 永远空。aget_state 是 langgraph 0.6+ 暴露的 async
        # 变体,会 await checkpointer.aget_tuple。同步 MemorySaver / SqliteSaver
        # 也能正常用 aget_state(await 对非 coroutine 是 no-op)。
        snapshot = await agent.aget_state(astream_kwargs["config"])
        pending_interrupts = tuple(snapshot.interrupts) if snapshot.interrupts else ()
    except Exception as gs_exc:  # noqa: BLE001 — 边界统一收口
        logger.warning("WS get_state 失败,跳过 HITL state 兜底: %s", gs_exc)
        pending_interrupts = ()
    if pending_interrupts:
        logger.info(
            "WS HITL state.interrupts 捕获: session=%s, interrupts=%d",
            session_id,
            len(pending_interrupts),
        )
        for intr in pending_interrupts:
            last_event_id += 1
            frame = _serialize_hitl_request(intr.value, interrupt_id=str(intr.id), event_id=last_event_id)
            await websocket.send_json(frame)
            first_action = frame["actions"][0] if frame["actions"] else {}
            logger.info(
                "WS confirmation_request 发送: session=%s, tool=%s, target=%s",
                session_id,
                first_action.get("tool_name", "?"),
                first_action.get("target_path", "?"),
            )
        # 挂起状态已写到 checkpoint(__interrupt__ channel),无需进程内缓存
        return last_event_id, "", False, None, pending_interrupts

    if had_error:
        # 已经有 error 事件发出，StreamGuard 走完就不要再发 done
        return last_event_id, "", False, None, None

    # 正常结束：先做归一化 / token 估算 / 思考抽取 / 16 字符分块，
    # 然后按 token_usage → thinking → chunks → final → done 顺序发出去。
    response_text = ""
    if full_response:
        # 1) 归一化：把 <think> 替换为 <thinking>，前端用 <thinking> 标识思考段
        normalized = full_response.replace("<think>", "<thinking>").replace("</think>", "</thinking>")

        # 2) token_usage：估算 token + context 占用率
        # 范围:累积 prompt["messages"] + 本轮 assistant 响应 = 整个对话上下文,
        # 而不是只看本轮响应 —— UI 显示的 % 才跟 deepagents 实际 trigger
        # 决策用的 token 计数同源(都是 count_tokens_approximately)。
        # prompt 是 _run_agent_streaming 入参(line 484),自带 system 段
        # + 历史 + 本轮 user 消息;这里再 append 一个 assistant 角色 dict
        # 模拟刚生成的回复入库后的样子(下游 add_message 也是 assistant
        # role,所以格式对齐)。
        full_context_messages: list[dict[str, Any]] = list(prompt["messages"]) + [
            {"role": "assistant", "content": normalized}
        ]
        estimated_tokens, context_usage = _estimate_tokens(
            full_context_messages, context_window=CONFIG["context_window"]
        )
        token_usage_event_id = last_event_id + 1
        await websocket.send_json(
            {
                "type": "token_usage",
                "content": "",
                "token_count": estimated_tokens,
                "context_usage": context_usage,
                "event_id": token_usage_event_id,
            }
        )
        last_event_id = token_usage_event_id

        # 3) 抽取 <thinking>...</thinking> 内容（DOTALL 跨行），并从正文里剥掉
        thinking_parts = re.findall(r"<thinking>(.*?)</thinking>", normalized, flags=re.DOTALL)
        response_text = re.sub(r"<thinking>.*?</thinking>", "", normalized, flags=re.DOTALL).strip()

        if thinking_parts:
            all_thinking = "\n".join(part.strip() for part in thinking_parts)
            thinking_event_id = last_event_id + 1
            await websocket.send_json(
                {
                    "type": "thinking",
                    "content": all_thinking,
                    "event_id": thinking_event_id,
                }
            )
            last_event_id = thinking_event_id

        # 4) 16 字符分块发 chunk，再发 final
        if response_text:
            chunk_size = 16
            for i in range(0, len(response_text), chunk_size):
                chunk_event_id = last_event_id + 1
                await websocket.send_json(
                    {
                        "type": "chunk",
                        "content": response_text[i : i + chunk_size],
                        "event_id": chunk_event_id,
                    }
                )
                last_event_id = chunk_event_id

            final_event_id = last_event_id + 1
            await websocket.send_json(
                {
                    "type": "final",
                    "content": response_text,
                    "event_id": final_event_id,
                }
            )
            last_event_id = final_event_id

    # 可观测：发送 ``type=stats`` 元事件，把本次流的 StreamGuard 统计
    # 暴露给前端。顺序在 done 之前，确保 done 始终是流的最后一帧。
    # 错误路径不会发 stats（前面已 return），符合"错误即终止"语义。
    stats_event_id = last_event_id + 1
    fallbacks_count = 0
    if hasattr(agent, "stats") and isinstance(agent.stats, dict):
        fallbacks_count = int(agent.stats.get("fallbacks", 0))
    await websocket.send_json(
        {
            "type": "stats",
            "content": "",
            "event_id": stats_event_id,
            "retries": int(guard.stats.get("retries", 0)),
            "events_emitted": int(guard.stats.get("events_emitted", 0)),
            "fallbacks": fallbacks_count,
        }
    )
    last_event_id = stats_event_id

    return stats_event_id, response_text, True, None, None


async def _handle_resume_frame(websocket: WebSocket, data: dict) -> int | None:
    """处理客户端的 resume 帧：校验 token，回 resume_ack 或 error。

    Args:
        websocket: 目标 WebSocket 连接。
        data: 客户端发来的 JSON dict（应含 ``session_id`` 和 ``resume_token``）。

    Returns:
        校验通过时返回 ``last_event_id``（可用于下次 resume 起点）；
        校验失败返回 ``None``（错误事件已发到 ws）。
    """
    session_id = data.get("session_id", "")
    token = data.get("resume_token", "")

    if not session_id or not token:
        await websocket.send_json(
            {
                "type": "error",
                "error_code": "invalid_resume_token",
                "content": "缺少 session_id 或 resume_token",
            }
        )
        return None

    try:
        last_event_id = verify_token(token, session_id)
    except InvalidResumeToken as err:
        await websocket.send_json(
            {
                "type": "error",
                "error_code": "invalid_resume_token",
                "content": str(err),
            }
        )
        return None

    await websocket.send_json(
        {
            "type": "resume_ack",
            "session_id": session_id,
            "resume_from_event_id": last_event_id,
        }
    )
    return last_event_id


async def handle_websocket(
    websocket: WebSocket,
    *,
    get_agent: Callable[[], Any],
    channel_broadcasts: dict[str, Callable] | None = None,
    get_quality_pipeline: Callable[[], Any] | None = None,
    get_intent_llm: Callable[[], Any] | None = None,
) -> None:
    """WebSocket 主端点的业务逻辑（不含路由装饰器）。

    由 ``main.py`` 用 ``@app.websocket(f"{API_PREFIX}/ws")`` 装饰一个薄壳函数
    调用本函数。业务依赖通过参数注入，避免与 ``main.py`` 循环 import。

    Args:
        websocket: FastAPI 注入的 WebSocket 连接。
        get_agent: 无参可调用，返回当前 Agent 实例（线程安全）。
            通常用 ``lambda: _agent``，并在 ``main.py`` 中通过 ``_agent_lock``
            保证一致性。
        channel_broadcasts: dict[channel_type_value -> async fn],WS 客户端连接时
            给 Gateway 注入广播,Gateway.route_message 走完会把响应推给所有
            注入的 broadcast。``None`` 或空 dict 表示不广播(仅 WS 自用)。
        get_quality_pipeline: Phase 2 Task 2.5：返回 ``QualityPipeline`` 实例
            的无参可调用。``None`` 或返回 ``None`` 时跳过质量门（向后兼容）。
        get_intent_llm: Phase 2 Task 3：返回分类用 ``BaseChatModel`` 实例
            的无参可调用（建议复用 quality pipeline 的 ``judge_llm``）。
            ``None`` 或返回 ``None`` 时跳过分类，intent 列落 ``chitchat`` 兜底。
    """
    # 注册客户端
    with _clients_lock:
        _ws_clients.append(websocket)

    # 注入 WS 广播到 Gateway (C4 重构,取代旧的 wechat_callback 单回调)
    if channel_broadcasts:
        from ..channels.base import ChannelType  # noqa: N814

        gateway = getattr(websocket.app.state, "gateway", None)
        if gateway is not None:
            for ch_type_str, fn in channel_broadcasts.items():
                gateway.set_broadcast(ChannelType(ch_type_str), fn)

    # 会话管理
    from ..sessions import get_session_manager

    session_manager = get_session_manager()
    session_id = None

    try:
        while True:
            # 内层 try 单独接住 receive_json 抛的 JSONDecodeError(心跳 ping /
            # 空字符串 / 意外数据),continue 重新 receive,不让 handler 整体退出。
            # 之前只在外层 except JSONDecodeError 里 log warn 然后函数结束,
            # 等价于 ws 关闭,客户端重连后又会被下一个 ping 杀掉,死循环。
            try:
                data = await websocket.receive_json()
            except json.JSONDecodeError as err:
                logger.warning("WS 收到非 JSON 帧: %s — 跳过并继续监听", err)
                continue

            # 1) resume 帧：单独处理，不进入主消息流
            if data.get("type") == "resume":
                await _handle_resume_frame(websocket, data)
                continue

            # 1.5) confirmation_response 帧:HITL 决策续流。
            # 取出 _session_hitl_state 中挂起的 interrupt + 把决策装成
            # ``Command(resume={"decisions": [...]})`` 续流。如果又触发
            # 新的 HITL,pending2 非空 → 回到 while True 顶部继续等待。
            if data.get("type") == _EVT_CONFIRMATION_RESPONSE:
                logger.info(
                    "WS confirmation_response 接收: session=%s event_id=%s interrupt_id=%s",
                    session_id,
                    data.get("event_id"),
                    data.get("interrupt_id"),
                )
                if session_id is None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error_code": "no_pending_interrupt",
                            "content": "当前没有待处理的中断",
                        }
                    )
                    continue
                interrupt_id = data.get("interrupt_id", "")  # noqa: F841 — 留作审计/日志,挂起项匹配由 checkpoint 接管
                decision = data.get("decision", "reject")
                if decision not in {"approve", "reject"}:
                    logger.warning("confirmation_response decision 无效: %s", decision)
                    continue
                # 从 checkpoint 读挂起 interrupt:langgraph 0.6+ 把 interrupt 存到
                # ``__interrupt__`` channel,aget_state().interrupts 拿回。
                # 多 worker 部署天然兼容(共享 nexus.db)。
                agent = get_agent()
                try:
                    snapshot = await agent.aget_state({"configurable": {"thread_id": session_id}})
                    pending_interrupts_for_resume = tuple(snapshot.interrupts) if snapshot.interrupts else ()
                except Exception as gs_exc:  # noqa: BLE001
                    logger.warning("WS confirmation_response get_state 失败: %s", gs_exc)
                    pending_interrupts_for_resume = ()
                logger.info(
                    "WS confirmation_response aget_state: session=%s pending=%d",
                    session_id,
                    len(pending_interrupts_for_resume),
                )
                if not pending_interrupts_for_resume:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error_code": "no_pending_interrupt",
                            "content": "当前没有待处理的中断",
                        }
                    )
                    continue
                # HITL 期望的 resume payload:{"decisions": [{"type": ...}, ...]}
                resume_payload: dict[str, Any] = {
                    "decisions": [{"type": decision} for _ in pending_interrupts_for_resume]
                }
                # confirmation_response 路径不需要走 user 消息的 _classify_and_record
                # 等流程,但 _run_agent_streaming 仍要 prompt 入参。command_resume
                # 非空时,prompt["messages"] 会被忽略(改走 Command(resume=...))。
                resume_prompt: dict[str, Any] = {"messages": []}
                (
                    last_event_id,
                    response_text,
                    stream_completed,
                    clarification,
                    pending_interrupts,
                ) = await _run_agent_streaming(
                    websocket,
                    session_id,
                    resume_prompt,
                    agent,
                    resume_from_event_id=None,
                    command_resume=resume_payload,
                )
                # 二次 HITL 触发:仅打日志,真正"挂起等下次 confirmation_response"
                # 的早返回由 ``_finalize_after_stream`` 内部判断 pending_interrupts 完成。
                if pending_interrupts is not None:
                    logger.info(
                        "WS HITL 二次挂起: session=%s, interrupts=%d",
                        session_id,
                        len(pending_interrupts),
                    )
                # 统一 finalize:澄清挂起 / HITL 挂起 / 质量门 / 入库 / done / emit ChatEnd。
                # WHY:ca6dec5 之前这里依赖 fall through 到 user 消息路径的 quality_gate /
                # add_message / done,但 confirmation_response 帧的 content 为空,会被
                # 下面 ``if not user_content: continue`` 拦截,导致 approve 后 LLM
                # 续流响应既不入库也不发 done。统一走 helper 消除路径分叉。
                await _finalize_after_stream(
                    websocket=websocket,
                    session_id=session_id,
                    user_content="",  # confirmation_response 不是 user 消息
                    message_id=str(uuid.uuid4()),  # 续流后用新 message_id 关联 ChatEnd
                    chat_start_monotonic=time.monotonic(),  # 续流重新计时
                    intent_result=DEFAULT_INTENT,  # chitchat fallback(没有 intent 分类)
                    last_event_id=last_event_id,
                    response_text=response_text,
                    stream_completed=stream_completed,
                    clarification=clarification,
                    pending_interrupts=pending_interrupts,
                    agent=agent,
                    get_quality_pipeline=get_quality_pipeline,
                )
                continue  # 本轮处理完,等下一次输入

            # 2) 普通用户消息帧
            user_content = data.get("content", "")

            if not user_content:
                continue

            # 创建或获取会话。客户端可在 body 传 session_id(用于多轮/续传),
            # 也可不传(让服务端自动分配)。无论谁给的 id,都需保证 sessions 表
            # 里有该行,否则 add_message 会触发 FK constraint 失败。
            # 旧实现只在 session_id is None 时才 create_session,导致客户端
            # 传新 id 时直接 FK 失败 — 2026-06 E2E 用例 8/11 复现,详见 task #42。
            from ..db import create_session, get_session

            new_session_created = False
            title = ""
            client_supplied_id: str | None = None
            if session_id is None:
                client_supplied_id = data.get("session_id")
                if not client_supplied_id:
                    # 客户端没传,服务端生成新 id
                    session_id = str(uuid.uuid4())
                    client_title = (data.get("title") or "").strip()
                    if client_title:
                        title = client_title
                    else:
                        cleaned = user_content.strip().replace("\n", " ")
                        title = cleaned[:30] + ("…" if len(cleaned) > 30 else "")
                        if not title:
                            title = "新会话"
                    create_session(session_id, title=title, channel="main")
                    new_session_created = True
                else:
                    # 客户端传了 id,先用它,再 ensure DB 行存在
                    session_id = client_supplied_id
                    if get_session(session_id) is None:
                        client_title = (data.get("title") or "").strip()
                        if client_title:
                            title = client_title
                        else:
                            cleaned = user_content.strip().replace("\n", " ")
                            title = cleaned[:30] + ("…" if len(cleaned) > 30 else "")
                            if not title:
                                title = "新会话"
                        create_session(session_id, title=title, channel="main")
                        # 客户端用的 id 是新的(此前 DB 无),发 session_created
                        # 让客户端拿回服务端认可的 title 字段
                        new_session_created = True

            if new_session_created:
                await websocket.send_json(
                    {
                        "type": "session_created",
                        "session_id": session_id,
                        "title": title,
                    }
                )

            # 提前生成 message_id,统一一处:让 ChatStart / IntentClassified /
            # QualityVerdict / ChatEnd / 入库 都用同一份。
            # ChatStart 必须紧跟消息接收发出,作为本次 chat 的起点标记。
            message_id = str(uuid.uuid4())
            chat_start_monotonic = time.monotonic()
            emit_chat_event(
                ChatStart(
                    timestamp=datetime.now(tz=UTC).isoformat(),
                    event="chat.start",
                    session_id=session_id,
                    message_id=message_id,
                    content_len=len(user_content),
                )
            )

            # 添加用户消息到历史(intent 由意图识别层落库)
            intent_classified_at = time.monotonic()
            intent_result = await _classify_and_record(get_intent_llm, session_id, user_content)
            intent_latency_ms = int((time.monotonic() - intent_classified_at) * 1000)
            emit_chat_event(
                IntentClassified(
                    timestamp=datetime.now(tz=UTC).isoformat(),
                    event="intent.classified",
                    session_id=session_id,
                    message_id=message_id,
                    intent=intent_result,
                    latency_ms=intent_latency_ms,
                    fallback=False,
                )
            )

            # 使用 SessionManager 构建带记忆的 prompt
            prompt = session_manager.build_prompt(session_id, user_content)

            # 可选：客户端在消息帧中携带 resume_token（兼容旧客户端）
            resume_from_event_id: int | None = None
            if data.get("resume_token"):
                try:
                    resume_from_event_id = verify_token(data["resume_token"], session_id)
                except InvalidResumeToken:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error_code": "invalid_resume_token",
                            "content": "消息中的 resume_token 无效",
                        }
                    )
                    continue

            # 运行 agent 流（已自带 StreamGuard + error_code/retryable）
            agent = get_agent()
            (
                last_event_id,
                response_text,
                stream_completed,
                clarification,
                pending_interrupts,
            ) = await _run_agent_streaming(websocket, session_id, prompt, agent, resume_from_event_id)

            # HITL 挂起分支:仅打日志,真正 early-return 等 confirmation_response
            # 由 ``_finalize_after_stream`` 内部处理(避免重复写 placeholder)。
            if pending_interrupts is not None:
                logger.info(
                    "WS HITL 挂起: session=%s, interrupts=%d",
                    session_id,
                    len(pending_interrupts),
                )

            # 统一 finalize:澄清挂起 / HITL 挂起 / 质量门 / 入库 / done / emit ChatEnd。
            # 复用 ``_finalize_after_stream`` 是关键 —— 它是 confirmation_response 续流
            # 路径也走的一段,确保 approve 后 LLM 续流的响应会发 done + 入库 + emit ChatEnd。
            await _finalize_after_stream(
                websocket=websocket,
                session_id=session_id,
                user_content=user_content,
                message_id=message_id,
                chat_start_monotonic=chat_start_monotonic,
                intent_result=intent_result,
                last_event_id=last_event_id,
                response_text=response_text,
                stream_completed=stream_completed,
                clarification=clarification,
                pending_interrupts=pending_interrupts,
                agent=agent,
                get_quality_pipeline=get_quality_pipeline,
            )

    except WebSocketDisconnect as wsd:
        logger.info(
            "客户端断开连接: session=%s code=%s reason=%s",
            session_id,
            getattr(wsd, "code", "?"),
            getattr(wsd, "reason", "?"),
        )
        with _clients_lock:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)
    except RuntimeError as err:
        # Starlette 竞态:客户端断开 → 我们已发 close message → 后续 send_json 抛
        # "Cannot call 'send' once a close message has been sent." 不影响业务,
        # 仅在日志里 stacktrace。降级为 info 避免污染告警。
        if "close message has been sent" in str(err):
            logger.info("WS 已关闭,跳过残留 send: %s", err)
        else:
            raise
    except Exception as err:  # noqa: BLE001 — 最后兜底,任何未预期异常不应击穿进程
        logger.exception("handle_websocket 未预期异常: %s", err)
