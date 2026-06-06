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

import logging
import re
import threading
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect

from ..config import CONFIG
from ..llm.policies import RetryPolicy
from ..resilience.resume import (
    InvalidResumeToken,
    make_token,
    verify_token,
)
from ..resilience.stream_guard import StreamGuard

logger = logging.getLogger(__name__)

# WS 流式响应的默认重试策略（基延迟 0.1s，上限 2s，±20% 抖动）
WS_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay=0.1, max_delay=2.0, jitter=0.2)

# 当前已注册的 WebSocket 客户端列表（供微信等外部通道在主循环中广播）
_ws_clients: list[WebSocket] = []
_clients_lock = threading.RLock()


# 不可重试的错误码集合（与 StreamGuard 的 _map_error_code 输出对齐）
_NON_RETRYABLE_ERROR_CODES = frozenset({"auth", "bad_request", "context_length", "content_filter"})


def _estimate_tokens(text: str, context_window: int = 32000) -> tuple[int, int]:
    """估算 token 数量和上下文使用率。

    字符 → token 换算（与 OpenAI 经验值对齐）：
      - 中文字符 × 2.5（中文 token 化比英文密）
      - 英文字符 × 0.25（GPT-style BPE 约 4 字符 1 token）
      - 其他字符 × 0.5（标点/数字/混合）

    Args:
        text: 文本内容（通常是被估算的"已用上下文"——累积 prompt 或本轮回复）。
        context_window: 模型的上下文窗口（token 数）。
            主流模型：GPT-3.5-turbo 16K, GPT-4 8K/32K, Claude 200K,
            MiniMax-M3 32K。默认 32000，可通过 CONFIG['context_window'] 覆盖。

    Returns:
        ``(token_count, context_usage_percent)``：
          - ``token_count``：估算的 token 数
          - ``context_usage_percent``：相对 ``context_window`` 的占用百分比
            （0.0-100.0，保留 1 位小数）
    """
    chinese_chars = len(re.findall(r"[一-鿿]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    other_chars = len(text) - chinese_chars - english_chars
    estimated_tokens = int(chinese_chars * 2.5 + english_chars * 0.25 + other_chars * 0.5)
    # 防 0 除
    if context_window <= 0:
        context_window = 32000
    # 保留 1 位小数，让"用了 0.5%"也能显示
    context_usage = round(estimated_tokens / context_window * 100, 1)
    return estimated_tokens, min(context_usage, 100.0)


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


async def _run_agent_streaming(
    websocket: WebSocket,
    session_id: str,
    prompt: dict,
    agent: Any,
    resume_from_event_id: int | None = None,
) -> tuple[int, str]:
    """运行 agent 流式响应，把事件转发到 WebSocket。

    使用 :class:`StreamGuard` 包装 ``agent.astream_events``：
      - 给每个事件附加进程内单调递增的 ``event_id``
      - 可重试错误自动重试；不可重试 / 重试用尽 → yield 1 个 error 事件
      - 永不抛异常（StreamGuard 已保证），调用方不需要再 try/except

    Args:
        websocket: 目标 WebSocket 连接。
        session_id: 会话 ID（用于日志上下文）。
        prompt: 已构建好的 prompt dict（含 ``messages``）。
        agent: 当前 Agent 实例（由 ``main.py`` 在调用时通过 ``get_agent()`` 注入）。
        resume_from_event_id: 客户端断点续传位置；Phase 1 简化模型下
            仅作为"客户端告知 server 上次看到哪"，不做真正的去重过滤
            （每次流都有新的 event_id 序列）。

    Returns:
        ``(last_event_id, response_text)``：
          - ``last_event_id`` 本次流结束时的最后一个 event_id（供下次签发 resume token）。
          - ``response_text`` 剥离 ``<thinking>`` 标签后的纯回复文本（用于 DB 存储）。
            错误路径返回空字符串。
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
        return 1, ""

    # StreamGuard 包 astream_events；每次重试会重新调一次 astream_events
    # （幂等重试，由上游 LLM 自行决定是否真幂等）。
    guard = StreamGuard(
        astream_events=lambda input, **kw: agent.astream_events(input, **kw),
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
    async for event in guard.astream_events({"messages": prompt["messages"]}, version="v2"):
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
                return last_event_id, ""
            # 可重试但 StreamGuard 仍 yield error，意味着情况特殊
            # （理论上不会到这里，StreamGuard 内部就用尽了）。安全起见停止。
            return last_event_id, ""

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
        elif event_type == "on_tool_start":
            tool_name = event.get("name", "未知工具")
            await websocket.send_json(
                {
                    "type": "thinking",
                    "content": f"[调用工具] {tool_name}",
                    "event_id": event_id,
                }
            )
        elif event_type == "on_tool_end":
            output = event.get("data", {}).get("output")
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

    if had_error:
        # 已经有 error 事件发出，StreamGuard 走完就不要再发 done
        return last_event_id, ""

    # 正常结束：先做归一化 / token 估算 / 思考抽取 / 16 字符分块，
    # 然后按 token_usage → thinking → chunks → final → done 顺序发出去。
    response_text = ""
    if full_response:
        # 1) 归一化：把 <think> 替换为 <thinking>，前端用 <thinking> 标识思考段
        normalized = full_response.replace("<think>", "<thinking>").replace("</think>", "</thinking>")

        # 2) token_usage：估算 token + context 占用率
        estimated_tokens, context_usage = _estimate_tokens(
        normalized, context_window=CONFIG.get("context_window", 32000)
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

    done_event_id = last_event_id + 1
    await websocket.send_json(
        {
            "type": "done",
            "content": "",
            "event_id": done_event_id,
        }
    )
    return done_event_id, response_text


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
    wechat_callback: Callable | None = None,
    get_quality_pipeline: Callable[[], Any] | None = None,
) -> None:
    """WebSocket 主端点的业务逻辑（不含路由装饰器）。

    由 ``main.py`` 用 ``@app.websocket(f"{API_PREFIX}/ws")`` 装饰一个薄壳函数
    调用本函数。业务依赖通过参数注入，避免与 ``main.py`` 循环 import。

    Args:
        websocket: FastAPI 注入的 WebSocket 连接。
        get_agent: 无参可调用，返回当前 Agent 实例（线程安全）。
            通常用 ``lambda: _agent``，并在 ``main.py`` 中通过 ``_agent_lock``
            保证一致性。
        wechat_callback: 微信消息回调（``_handle_wechat_message``），用于在
            客户端连接时给微信通道挂上广播。``None`` 表示不挂（仅 WS 自用）。
        get_quality_pipeline: Phase 2 Task 2.5：返回 ``QualityPipeline`` 实例
            的无参可调用。``None`` 或返回 ``None`` 时跳过质量门（向后兼容）。
    """
    # 注册客户端
    with _clients_lock:
        _ws_clients.append(websocket)

    # 设置微信消息回调
    if wechat_callback is not None:
        from ..channels.wechat import get_active_wechat_channel

        channel = get_active_wechat_channel()
        if channel:
            channel.on_message(wechat_callback)

    # 会话管理
    from ..sessions import get_session_manager

    session_manager = get_session_manager()
    session_id = None

    try:
        while True:
            data = await websocket.receive_json()

            # 1) resume 帧：单独处理，不进入主消息流
            if data.get("type") == "resume":
                await _handle_resume_frame(websocket, data)
                continue

            # 2) 普通用户消息帧
            user_content = data.get("content", "")

            if not user_content:
                continue

            # 创建或获取会话
            new_session_created = False
            title = ""
            if session_id is None:
                session_id = data.get("session_id")
                if not session_id:
                    from ..db import create_session

                    session_id = str(uuid.uuid4())
                    title = data.get("title") or "新会话"
                    create_session(session_id, title=title, channel="main")
                    new_session_created = True

            if new_session_created:
                await websocket.send_json(
                    {
                        "type": "session_created",
                        "session_id": session_id,
                        "title": title,
                    }
                )

            # 添加用户消息到历史
            from ..db import add_message

            add_message(str(uuid.uuid4()), session_id, "user", user_content)

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
            last_event_id, response_text = await _run_agent_streaming(
                websocket, session_id, prompt, agent, resume_from_event_id
            )

            # Phase 2 Task 2.5：质量门。对 raw_response 跑 RubricJudge + Repair；
            # verdict 决定入库文本（ACCEPT→raw / REPAIR→重生 / REJECT→fallback）。
            # pipeline 失败/未配置时降级用原 response_text。
            pipeline = get_quality_pipeline() if get_quality_pipeline else None
            if pipeline is not None and response_text:
                try:
                    pipeline.set_session_id(session_id)
                    final = await pipeline.run_with_quality(
                        question=user_content,
                        raw_response=response_text,
                    )
                    # 若 verdict 改变最终文本（如 REJECT 用了 fallback），
                    # 补发一个 final 帧给客户端（不重发 chunk，避免重复）
                    if final.response_text != response_text:
                        replacement_event_id = last_event_id + 1
                        await websocket.send_json(
                            {
                                "type": "final",
                                "content": final.response_text,
                                "event_id": replacement_event_id,
                            }
                        )
                        last_event_id = replacement_event_id
                    response_text = final.response_text
                except Exception as exc:  # noqa: BLE001 — 质量门异常不污染主流程
                    logger.warning("QualityPipeline 失败，使用原回复: %s", exc)

            # 签发新 resume token 给客户端（仅在配置了 secret 且会话建立后）
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

            # 保存助手回复到数据库（用剥离 <thinking> 后的纯文本，避免 DB 存原始含标签内容）
            if response_text:
                add_message(str(uuid.uuid4()), session_id, "assistant", response_text)

    except WebSocketDisconnect:
        logger.info("客户端断开连接")
        with _clients_lock:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)
