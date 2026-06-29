"""流结束后的统一收尾 + HITL 帧序列化 + resume 帧处理。

模块化拆分后,``api/ws/handlers.py`` 在流结束后统一调
:func:`_finalize_after_stream`(澄清挂起 / HITL 挂起 / 质量门 / 入库 /
done / emit ChatEnd 都在一处);:func:`_serialize_hitl_request` 把 langchain
HITL 标准 payload 翻成 WS 前端友好视图;:func:`_handle_resume_frame` 校验
断线重连 token。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

from ...db import add_message
from ...resilience.resume import (
    InvalidResumeToken,
    make_token,
    verify_token,
)
from .observability import _emit_chat_end

__all__ = [
    "_finalize_after_stream",
    "_serialize_hitl_request",
    "_handle_resume_frame",
    "_EVT_CONFIRMATION_REQUEST",
]


logger = logging.getLogger(__name__)

# WS 帧类型常量
_EVT_CONFIRMATION_REQUEST = "confirmation_request"


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
    """流结束后的统一收尾:澄清挂起 / HITL 挂起 / 质量门 / 入库 / done / emit ChatEnd。

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
    # 澄清挂起:把 ask_user 调用 + 问题追加到会话历史(作为 assistant 角色),
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

    # HITL 挂起:``_run_agent_streaming`` 已经发了 ``confirmation_request`` +
    # 写入 ``_session_hitl_state``,这里什么都不做(等 ``confirmation_response``)。
    if pending_interrupts is not None:
        return

    # 质量门 2026-06-29 重构:QualityPipeline 自造模块已删除,质量门由
    # deepagents RubricMiddleware 在 agent 内部驱动(见 agent.py 中间件链)。
    # ws.py 不再显式调用 pipeline,response_text 直接走后续入库 / resume token 流程。
    final_response: Any = None

    # 签发新 resume token 给客户端(仅在配置了 secret 且会话建立后)
    if session_id and last_event_id > 0:
        try:
            new_token = make_token(session_id, last_event_id)
        except RuntimeError:
            # CONFIG 中 resume_secret 未配置或过弱 → 静默不签发
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


async def _handle_resume_frame(websocket: WebSocket, data: dict) -> int | None:
    """处理客户端的 resume 帧:校验 token,回 resume_ack 或 error。

    Args:
        websocket: 目标 WebSocket 连接。
        data: 客户端发来的 JSON dict(应含 ``session_id`` 和 ``resume_token``)。

    Returns:
        校验通过时返回 ``last_event_id``(可用于下次 resume 起点);
        校验失败返回 ``None``(错误事件已发到 ws)。
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
