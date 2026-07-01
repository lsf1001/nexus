"""WebSocket 主端点 ``handle_websocket`` 及客户端注册 / 断连处理。

模块化拆分后,本模块集中承载:

- :func:`handle_websocket` — WS 主端点业务逻辑(不含路由装饰器),
  由 ``main.py`` 用 ``@app.websocket`` 装饰薄壳调入
- 主消息循环:resume 帧 / confirmation_response 帧 / 普通 user 消息帧
- 客户端注册 / 解注册:依赖 :mod:`.registry` 的 register / unregister
- Gateway 广播注入:channel_broadcasts 在 WS 连接时给 Gateway 注入

业务依赖(``get_agent`` / ``channel_broadcasts`` / ``get_quality_pipeline``)
通过参数注入到 :func:`handle_websocket`,避免与 ``main.py`` 循环 import。

WHY 单独成包:旧 ``api/ws.py`` 1386 行超 800 上限,主端点 + 注册表 +
鉴权 + 流式循环混在一起,职责不清晰。拆出后,本模块仅 350 行左右,只
负责 WS 主循环。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ...db import create_session, get_session, update_session
from ...intent.router import DEFAULT_INTENT
from ...observability import ChatStart, IntentClassified
from ...resilience.resume import InvalidResumeToken, verify_token
from ...sessions import get_session_manager
from .finalize import _finalize_after_stream
from .observability import emit_chat_event
from .registry import (
    register,
    unregister,
)
from .streaming import (
    _EVT_CONFIRMATION_RESPONSE,
    _classify_and_record,
    _run_agent_streaming,
)

__all__ = ["handle_websocket"]


logger = logging.getLogger(__name__)


# 模块级 ``get_agent`` shim:运行时透传 ``main._get_current_agent``。
# 为什么不在 ``import`` 时直接 ``from ...main import _get_current_agent as get_agent``:
# ``main.py`` 顶层 ``from .api.ws import handle_websocket`` 引入循环。延后到首次调用
# 时解析:本模块是 leaf(无反向 import 副作用),首次进 handle_websocket 时
# main 已经 import 完,可安全引用。测试可通过 ``monkeypatch.setattr(h, "get_agent", ...)``
# 在模块级替换,行为与生产一致。
def get_agent() -> Any:
    """返回当前 Agent 实例(从 main 模块懒解析,见上方说明)。"""
    from ... import main as _main

    return _main._get_current_agent()


# confirmation_response 路径 aget_state 进程内缓存:
# 同 session 在用户决策窗口(< 1s)内连续读复用缓存,避免每次都走 SQLite hit。
# 失败结果不缓存(transient 故障需要下次重试);HITL 完成时显式 invalidate。
#
# Cache 内存上界:每个 session_id 一个 entry,TTL 1s,read-miss 时自动覆盖;
# 无显式 LRU eviction 但实际只受"曾出现过的 session_id 数"约束,
# DMG 端正常使用下远低于 1 万,内存占用可忽略(每 entry ~100 字节)。
_INTERRUPTS_CACHE_TTL_SECONDS: float = 1.0
_interrupts_cache: dict[str, tuple[float, tuple[Any, ...]]] = {}


@dataclass(frozen=True, slots=True)
class _InterruptsLookup:
    """``_resolve_pending_interrupts`` 的返回值,带缓存命中状态。

    WHY 集中:把 interrupts tuple + cache_status + agent 三者打包,避免
    handler 端重复 ``_interrupts_cache.get`` + ``now - cached[0]`` 判定
    (cache_status 在 helper 内部已计算一次,handler 不应再算);同时省掉
    handler 端第二次 ``get_agent()`` 调用(复用 helper 已解析的 agent)。
    """

    interrupts: tuple[Any, ...]
    cache_status: str  # "hit" / "miss" / "fail"
    agent: Any


async def _resolve_pending_interrupts(session_id: str) -> _InterruptsLookup:
    """读 session 待处理 interrupts,带 1s TTL 进程内缓存。

    WHY 缓存:同一 session 在短时间内的连续 confirmation_response / 续流
    操作会重复调 ``agent.aget_state`` 读 checkpoint(每次都走 SQLite hit)。
    1s TTL 覆盖典型 confirmation_response 流程(用户决策时间通常 < 1s),
    同时保证 stale 数据不会停留过久。

    缓存命中条件:
      - session_id 存在于 ``_interrupts_cache``
      - 当前时间距上次写入 < ``_INTERRUPTS_CACHE_TTL_SECONDS``

    失败结果**不**写入缓存(transient 故障让下次重试,HITL 状态可恢复)。

    Args:
        session_id: 会话 id,作为缓存 key 和 aget_state 的 thread_id。

    Returns:
        ``_InterruptsLookup`` 含:
          - ``interrupts``: ``(Interrupt, ...)`` tuple,空挂起或 aget_state 失败时为 ``()``
          - ``cache_status``: ``"hit"`` (TTL 内复用) / ``"miss"`` (新读) /
            ``"fail"`` (aget_state 抛异常,**不**写入缓存)
          - ``agent``: 已解析的 Agent 实例,handler 可直接用,无需再 ``get_agent()``
    """
    now = time.monotonic()
    cached = _interrupts_cache.get(session_id)
    if cached is not None and (now - cached[0]) < _INTERRUPTS_CACHE_TTL_SECONDS:
        # 命中:agent 此时不需要(handler 多半已经有),但仍取一次保合约
        return _InterruptsLookup(interrupts=cached[1], cache_status="hit", agent=get_agent())
    agent = get_agent()
    try:
        snapshot = await agent.aget_state({"configurable": {"thread_id": session_id}})
        interrupts: tuple[Any, ...] = tuple(snapshot.interrupts) if snapshot.interrupts else ()
        _interrupts_cache[session_id] = (now, interrupts)
        return _InterruptsLookup(interrupts=interrupts, cache_status="miss", agent=agent)
    except Exception as gs_exc:  # noqa: BLE001 — 边界统一收口
        logger.warning("WS confirmation_response get_state 失败: %s", gs_exc, exc_info=True)
        # 失败不写入缓存 — transient 故障让下次重试
        return _InterruptsLookup(interrupts=(), cache_status="fail", agent=agent)


def _invalidate_interrupts_cache(session_id: str) -> None:
    """HITL 完成一轮后显式失效缓存,确保下一次会重读。

    调时机:
      - ``_run_agent_streaming`` 末尾(无论成功 / HITL 完成 / 错误)
      - 任何写 checkpoint 状态的副作用之后(目前没有其它写路径,留扩展位)

    Args:
        session_id: 要失效的会话 id;不存在时静默 no-op(``pop`` 默认行为)。
    """
    _interrupts_cache.pop(session_id, None)


async def handle_websocket(
    websocket: WebSocket,
    *,
    get_agent: Callable[[], Any],
    channel_broadcasts: dict[str, Callable] | None = None,
    get_quality_pipeline: Callable[[], Any] | None = None,
) -> None:
    """WebSocket 主端点的业务逻辑(不含路由装饰器)。

    由 ``main.py`` 用 ``@app.websocket(f"{API_PREFIX}/ws")`` 装饰一个薄壳函数
    调用本函数。业务依赖通过参数注入,避免与 ``main.py`` 循环 import。

    2026-06-29 重构:``get_intent_llm`` 参数已删除 — IntentClassifier
    自造模块下线(intent/router.py 改用纯函数正则推断),不再需要
    注入 intent LLM。

    Args:
        websocket: FastAPI 注入的 WebSocket 连接。
        get_agent: 无参可调用,返回当前 Agent 实例(线程安全)。
            通常用 ``lambda: _agent``,并在 ``main.py`` 中通过 ``_agent_lock``
            保证一致性。
        channel_broadcasts: dict[channel_type_value -> async fn],WS 客户端连接时
            给 Gateway 注入广播,Gateway.route_message 走完会把响应推给所有
            注入的 broadcast。``None`` 或空 dict 表示不广播(仅 WS 自用)。
        get_quality_pipeline: Phase 2 Task 2.5:返回 ``QualityPipeline`` 实例
            的无参可调用。``None`` 或返回 ``None`` 时跳过质量门(2026-06-29
            起 QualityPipeline 已删除,质量门由 deepagents RubricMiddleware
            驱动;本参数保留为 no-op 兼容层)。
    """
    # 注册客户端
    register(websocket)

    # 注入 WS 广播到 Gateway (C4 重构,取代旧的 wechat_callback 单回调)
    if channel_broadcasts:
        from ...channels.base import ChannelType  # noqa: N814

        gateway = getattr(websocket.app.state, "gateway", None)
        if gateway is not None:
            for ch_type_str, fn in channel_broadcasts.items():
                gateway.set_broadcast(ChannelType(ch_type_str), fn)

    # 会话管理
    session_manager = get_session_manager()
    session_id = None
    # 本连接的 event_id 跨轮游标:_classify_and_record(心跳)与
    # _run_agent_streaming(主流)都会发帧,二者的 event_id 必须单调衔接,
    # 这样客户端用 event_id 续流时心跳也是合法 resume 标记。每轮
    # _run_agent_streaming 返回后用其 last_event_id 更新本变量,新轮的
    # 心跳就用本变量+1。
    last_event_id = 0

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

            # 1) resume 帧:单独处理,不进入主消息流
            if data.get("type") == "resume":
                from .finalize import _handle_resume_frame

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
                # 走 1s TTL 进程内缓存避免重复 SQLite hit(详见 _resolve_pending_interrupts)。
                result = await _resolve_pending_interrupts(session_id)
                pending_interrupts_for_resume = result.interrupts
                logger.info(
                    "WS confirmation_response aget_state: session=%s pending=%d (cache=%s)",
                    session_id,
                    len(pending_interrupts_for_resume),
                    result.cache_status,
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
                agent = result.agent
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
                    get_quality_pipeline=get_quality_pipeline,  # 2026-06-29: 改返 None(quality/pipeline.py 已删)
                )
                # invalidate 时机:resume 完成后 checkpoint 状态已变化,
                # 必须显式失效缓存让下一次 confirmation_response 重读最新状态。
                # 无论成功 / HITL 二次挂起 / 错误都要 invalidate。
                _invalidate_interrupts_cache(session_id)
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
                    else:
                        # 会话已存在:若客户端带了非空 title 则应用,避免用户改名
                        # 被静默丢弃。WHY:旧实现只走 ``if get_session is None``
                        # 分支,复用已有 session 时 ``data["title"]`` 直接被忽略,
                        # 前端改名 → 服务端不变 → 用户困惑。空 title 跳过以避免
                        # 每次普通聊天都触发无谓 UPDATE + 改 updated_at。
                        client_title = (data.get("title") or "").strip()
                        if client_title:
                            update_session(session_id, title=client_title)
                            title = client_title

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
            intent_result = await _classify_and_record(
                websocket,
                session_id,
                user_content,
                last_event_id=last_event_id,
            )
            # 心跳发出去的 event_id = last_event_id + 1:与下一轮 _run_agent_streaming
            # 的流内 event_id 保持单调衔接(让客户端拿 event_id 续流时心跳也是
            # 合法标记)。last_event_id 本身由 _run_agent_streaming 返回值在下方
            # 更新,跨轮游标在此维持。
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

            # 可选:客户端在消息帧中携带 resume_token(兼容旧客户端)
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

            # 运行 agent 流(已自带 StreamGuard + error_code/retryable)
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
        unregister(websocket)
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
