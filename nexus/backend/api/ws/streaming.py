"""Agent 流式响应循环:把 astream_events 转成 WS 帧。

模块化拆分后,本模块集中承载:

- :data:`WS_RETRY_POLICY` — 全局共享重试策略
- :data:`_NON_RETRYABLE_ERROR_CODES` — 不可重试的错误码集合
- :func:`_is_retryable_error_code` — 错误码 → 是否可重试
- :func:`_classify_and_record` — 正则 intent + 入库 + 心跳帧
- :func:`_estimate_tokens` — token 估算 + context_usage 百分比
- :func:`_run_agent_streaming` — StreamGuard 包装的主流循环,
  含 thinking / chunk 实时分发、ask_user 澄清挂起、HITL GraphInterrupt
  处理、token_usage / final / stats 帧尾。

``api/ws/handlers.py`` 调本模块的 :func:`_run_agent_streaming`,
``api/ws/finalize.py`` 调本模块的 :func:`_estimate_tokens`(流末 token_usage 帧)。

WHY 单独成包:旧 ``api/ws.py`` 1386 行超 800 上限,把这部分拆出后
``handlers.py`` / ``finalize.py`` 各自仅承载 WS 主循环和 finalize,
文件大小均回落到 §1.2 上限内。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import WebSocket

from ... import db as _db
from ...config import CONFIG
from ...intent.router import IntentKind, classify_intent
from ...llm.policies import RetryPolicy
from ...resilience.stream_guard import StreamGuard
from ..thinking_parser import ThinkingParser
from .finalize import _serialize_hitl_request

__all__ = [
    "WS_RETRY_POLICY",
    "_NON_RETRYABLE_ERROR_CODES",
    "_CLARIFY_TOOL_NAME",
    "_EVT_CLARIFICATION_REQUEST",
    "_EVT_CONFIRMATION_RESPONSE",
    "_is_retryable_error_code",
    "_classify_and_record",
    "_estimate_tokens",
    "_run_agent_streaming",
]


logger = logging.getLogger(__name__)

# WS 流式响应的默认重试策略(基延迟 0.1s,上限 2s,±20% 抖动)
WS_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay=0.1, max_delay=2.0, jitter=0.2)

# 不可重试的错误码集合(与 StreamGuard 的 _map_error_code 输出对齐)
_NON_RETRYABLE_ERROR_CODES = frozenset({"auth", "bad_request", "context_length", "content_filter"})

# 澄清工具名(与 nexus.backend.tools.ask_user.name 对齐)
_CLARIFY_TOOL_NAME = "ask_user"
# WS 帧类型常量
_EVT_CLARIFICATION_REQUEST = "clarification_request"
_EVT_CONFIRMATION_REQUEST = "confirmation_request"
_EVT_CONFIRMATION_RESPONSE = "confirmation_response"


async def _emit_chunks(
    websocket: WebSocket,
    parser: ThinkingParser,
    text: str | None,
    counter: dict,
    *,
    flush: bool = False,
) -> None:
    """三种调用点共用的 chunk 上行逻辑。

    Args:
        websocket: WS 连接
        parser: ThinkingParser 或同形接口(具 .feed() / .flush() 返回 ``[(kind, text), ...]``)
        text: feed 输入(None 时仅在 flush=True 用)
        counter: dict 含 event_id / last_event_id / emitted_chunk_text,按引用累加
        flush: True 走 parser.flush();否则 feed(text)
    """
    pairs = parser.flush() if flush else parser.feed(text or "")
    for kind, chunk_text in pairs:
        counter["event_id"] += 1
        counter["last_event_id"] = counter["event_id"]
        await websocket.send_json(
            {
                "type": kind,
                "content": chunk_text,
                "event_id": counter["event_id"],
            }
        )
        if kind == "chunk":
            counter["emitted_chunk_text"] += chunk_text


def _is_retryable_error_code(error_code: str) -> bool:
    """根据 wire 上的 ``error_code`` 判断是否还可重试。

    - ``*_exhausted`` 后缀表示重试已用尽 → 不可重试
    - ``auth`` / ``bad_request`` / ``context_length`` / ``content_filter`` 这类
      结构性错误即使没加 exhausted 后缀也不应再重试
    - 其余(``rate_limit`` / ``timeout`` / ``unknown``)视为可重试

    Args:
        error_code: 来自 StreamGuard 错误事件的 ``error_code`` 字段。

    Returns:
        是否还可重试。
    """
    if error_code.endswith("_exhausted"):
        return False
    return error_code not in _NON_RETRYABLE_ERROR_CODES


async def _classify_and_record(
    websocket: WebSocket,
    session_id: str,
    user_content: str,
    last_event_id: int = 0,
) -> IntentKind:
    """正则推断 intent + 把 user 消息(含 intent)写库。

    2026-06-29 重构:不再调 LLM 分类(对齐 DeepAgents 框架:意图分发由
    :class:`SubAgent` + Task 工具机制接管,业务级 intent 标记用正则同步
    推断即可,延迟 0、零 LLM 成本)。

    任何异常一律兜底 chitchat(最安全:不影响 task 工具链)。

    Args:
        websocket: WS 连接,用于发心跳帧。
        session_id: 会话 id,用于把 user 消息入库。
        user_content: 用户原始消息文本。
        last_event_id: 上一次流结束的 event_id(供 resume token 续点);心跳帧
            必须用 ``last_event_id + 1`` 以保持客户端单调计数,让该帧也可作为
            合法 resume 标记。首轮 / 无历史时传 0。
    """
    # === 心跳:让前端立刻看到反馈,避免 agnes 慢模型 16s+ spinner ===
    # WHY 2026-06-28:agent 流式响应要 16s+ (agnes),期间前端 isLoading=true
    # 但收不到任何 WS 帧,用户体感"卡死"。先发一个 thinking 帧告诉用户
    # "正在识别你的意图",让前端立刻有反馈。
    # event_id=last_event_id+1:与 _run_agent_streaming 的 event_id 计数器
    # 单调衔接,保证客户端用 event_id 续流时心跳也是合法 resume 标记。
    intent_classify_event_id = last_event_id + 1
    try:
        await websocket.send_json(
            {
                "type": "thinking",
                "content": "正在识别你的意图…",
                "event_id": intent_classify_event_id,
            }
        )
    except Exception as heartbeat_exc:  # noqa: BLE001
        # 心跳失败不能让 intent 分类中断(可能 WS 已断但调用链未感知),记日志继续
        logger.warning("WS intent 心跳发送失败: %s", heartbeat_exc)

    # 同步正则推断 intent(classify_intent 内部已 try/except 兜底 chitchat)
    intent: IntentKind = classify_intent(user_content)
    # 入库(用 generate uuid;不传 thinking_content,跟 add_message 默认对齐)
    _db.add_message(str(uuid.uuid4()), session_id, "user", user_content, intent=intent)
    return intent


def _estimate_tokens(
    content: str | list,
    context_window: int = 200000,
) -> tuple[int, float]:
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


async def _run_agent_streaming(
    websocket: WebSocket,
    session_id: str,
    prompt: dict,
    agent: Any,
    resume_from_event_id: int | None = None,
    *,
    command_resume: dict[str, Any] | None = None,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None]:
    """WS 流式响应总编排(≤ 80 行,§1.2)。

    编排 3 步:
      1. 拼 astream input (``_emit_astream_kwargs``)
      2. 消费 astream 事件 (``_consume_astream_events``)
      3. 收尾 flush + final 帧 (``_finalize_stream``)

    Returns:
        ``(last_event_id, response_text, completed, clarification, pending_interrupts)``:
          - ``last_event_id`` 本次流结束时的最后一个 event_id(供下次签发 resume token)。
          - ``response_text`` 剥离 ``<thinking>`` 标签后的纯回复文本(用于 DB 存储)。
            错误 / HITL 挂起 路径返回空字符串。
          - ``completed`` 表示本次流是否正常完成;错误 / 澄清 / HITL 挂起路径不应再发 ``done``。
          - ``clarification`` ``(question, options)`` 当 LLM 调用 ``ask_user``
            时填入,handle_websocket 据此跳过质量门 + 跳过 ``done`` 帧。
          - ``pending_interrupts`` ``tuple[Interrupt, ...] | None`` 当 HITL 触发时填入,
            handle_websocket 据此挂起本轮流,等客户端发 confirmation_response 后用
            ``Command(resume=...)`` 新 astream 继续。
    """
    if agent is None:
        # 没可用 agent(极端情况:启动时没模型 key)
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

    guard, astream_kwargs_with_version, _counter, parser = _build_stream_guard(agent, session_id)
    astream_input = _emit_astream_kwargs(prompt, command_resume=command_resume)

    last_event_id, emitted_chunk_text, had_error, clarification, pending = await _consume_astream_events(
        agent,
        astream_input,
        websocket,
        parser,
        _counter,
        astream_kwargs=astream_kwargs_with_version,
        session_id=session_id,
        stream_guard=guard,
        resume_from_event_id=resume_from_event_id,
    )

    if had_error or clarification is not None or pending is not None:
        return last_event_id, "", False, clarification, pending

    last_event_id, response_text, completed = await _finalize_stream(
        websocket,
        parser,
        _counter,
        session_id=session_id,
        prompt=prompt,
        agent=agent,
        stream_guard=guard,
        last_event_id=last_event_id,
    )
    return last_event_id, response_text, completed, None, None


def _build_stream_guard(
    agent: Any,
    session_id: str,
) -> tuple[StreamGuard, dict[str, Any], dict[str, Any], ThinkingParser]:
    """组装 StreamGuard + astream kwargs + 状态 counter + parser。

    WHY 独立:StreamGuard 包装逻辑(GraphInterrupt 透传 + callback 挂载
    + thread_id 注入 + version=v2)与主流程无关;抽出来后主函数只看
    ``setup → consume → finalize`` 编排,§1.2 80 行限制可达。
    """
    astream_kwargs = _build_astream_kwargs_with_callbacks(agent, session_id)
    guard = StreamGuard(
        astream_events=_make_astream_factory(agent),
        retry_policy=WS_RETRY_POLICY,
        max_total_retries=2,
    )
    # v1 is deprecated since langchain-core 1.0; v2 keeps the same event
    # names (on_chat_model_stream / on_tool_start / on_tool_end) and the
    # same data shape (data.chunk / data.output), so the rest of the loop
    # works unchanged.
    astream_kwargs_with_version = {**astream_kwargs, "version": "v2"}
    counter: dict[str, Any] = {
        "event_id": 0,
        "last_event_id": 0,
        "emitted_chunk_text": "",
    }
    # 实时 chunk / thinking 分发器:每个 on_chat_model_stream 事件立即送进
    # parser,解析产出的 (kind, text) 帧立刻 send_json。ThinkingParser 同时
    # 识别 ``<thinking>...</thinking>`` 跨 chunk 标签分片,thinking 内容也
    # 实时送,不再缓存到流末做 re.findall。WHY 2026-06-28:旧实现把 chunk
    # 攒到 LLM 跑完才切碎发出,Agnes 慢模型场景前端 26 秒收不到帧;改为实时。
    parser = ThinkingParser()
    return guard, astream_kwargs_with_version, counter, parser


def _build_astream_kwargs_with_callbacks(agent: Any, session_id: str) -> dict[str, Any]:
    """拼 astream kwargs:挂 NexusLogHandler / verbose_handler + thread_id。

    checkpointer 必须配 thread_id 才能让 Command(resume=...) 找回挂起状态。
    session_id 单进程内唯一,直接当 thread_id。
    """
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
    existing_config = astream_kwargs.get("config") or {}
    astream_kwargs["config"] = {
        **existing_config,
        "configurable": {
            **dict(existing_config.get("configurable") or {}),
            "thread_id": session_id,
        },
    }
    return astream_kwargs


def _make_astream_factory(agent: Any):
    """构造 astream 工厂:透传 GraphInterrupt(不让 StreamGuard 吞掉)。

    StreamGuard 默认 ``except Exception`` 会把 GraphInterrupt 当 classified
    错误吞掉 yield error 事件——但 HITL 不是错误,它是 langgraph 设计的
    "图挂起"机制(继承 GraphBubbleUp)。``agent.astream_events`` 内部抛
    GraphInterrupt 发生在 async generator 的 ``__anext__`` 阶段,不在工厂
    调用瞬间,所以工厂必须自己消费 generator 并在内部 ``async for`` 处
    try/except 再 raise,让 StreamGuard 的外层 ``async for`` 捕获到。
    """
    from langgraph.errors import GraphInterrupt

    async def _astream_factory(input_: Any, **kw: Any) -> Any:
        agen = agent.astream_events(input_, **kw)
        try:
            async for event in agen:
                yield event
        except GraphInterrupt:
            raise

    return _astream_factory


def _emit_astream_kwargs(
    prompt: dict,
    *,
    command_resume: dict[str, Any] | None = None,
) -> Any:
    """构造 astream_events 的 input:Command(resume) 或 messages=prompt。

    WHY 独立:构造逻辑与主事件循环无关;抽出来后 ``_run_agent_streaming``
    主函数可以只看流程。
    """
    if command_resume is not None:
        from langgraph.types import Command

        return Command(resume=command_resume)
    return {"messages": prompt["messages"]}


async def _consume_astream_events(
    agent: Any,
    astream_input: Any,
    websocket: WebSocket,
    parser: ThinkingParser,
    counter: dict[str, Any],
    *,
    astream_kwargs: dict[str, Any],
    session_id: str,
    stream_guard: StreamGuard,
    resume_from_event_id: int | None,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None]:
    """主 astream 事件循环,封装 on_chat_model_stream / _end / on_tool_* /
    GraphInterrupt / state.interrupts 五类事件分发。

    Returns:
        ``(last_event_id, emitted_chunk_text, had_error, clarification, pending_interrupts)``
    """
    from langgraph.errors import GraphInterrupt

    last_event_id = 0
    had_error = False
    emitted_chunk_text = counter["emitted_chunk_text"]

    try:
        async for event in stream_guard.astream_events(astream_input, **astream_kwargs):
            event_id = int(event.get("event_id", 0))
            event_type = event.get("event")

            if event.get("type") == "error":
                return await _handle_stream_guard_error(websocket, event, event_id, emitted_chunk_text)

            # Phase 1 resume 过滤:跳过 event_id <= resume_from_event_id 的事件
            if resume_from_event_id is not None and event_id > 0 and event_id <= resume_from_event_id:
                last_event_id = max(last_event_id, event_id)
                continue

            if event_type == "on_chat_model_stream":
                event_id, last_event_id, emitted_chunk_text = await _emit_chat_model_chunk(
                    websocket, parser, event, event_id, last_event_id, emitted_chunk_text, counter
                )
            elif event_type == "on_chat_model_end":
                event_id, last_event_id, emitted_chunk_text = await _emit_chat_model_end_fallback(
                    websocket, parser, event, event_id, last_event_id, emitted_chunk_text, counter
                )
            elif event_type == "on_tool_start":
                result = await _handle_tool_start_event(
                    websocket, session_id, event, event_id, last_event_id, emitted_chunk_text
                )
                if result is not None:
                    return result
                last_event_id = max(last_event_id, event_id)
                continue
            elif event_type == "on_tool_end":
                await _handle_tool_end_event(websocket, session_id, event, event_id)

            if event_id > last_event_id:
                last_event_id = event_id
    except GraphInterrupt as gi:
        return await _handle_graph_interrupt(websocket, session_id, gi, last_event_id, emitted_chunk_text)

    last_event_id, emitted_chunk_text, pending_interrupts = await _drain_pending_hitl_interrupts(
        agent, websocket, session_id, astream_kwargs, last_event_id, emitted_chunk_text
    )
    if pending_interrupts is not None:
        return last_event_id, emitted_chunk_text, False, None, pending_interrupts

    counter["last_event_id"] = last_event_id
    counter["emitted_chunk_text"] = emitted_chunk_text
    return last_event_id, emitted_chunk_text, had_error, None, None


async def _handle_stream_guard_error(
    websocket: WebSocket,
    event: dict,
    event_id: int,
    emitted_chunk_text: str,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None]:
    """处理 StreamGuard 错误事件:发 error 帧并终止流。

    不可重试 / 已耗尽:停止流(不再发 done);返回空字符串避免把 raw 文本
    (含 thinking 标签)写入 DB。
    """
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
    return event_id, emitted_chunk_text, True, None, None


async def _emit_chat_model_chunk(
    websocket: WebSocket,
    parser: ThinkingParser,
    event: dict,
    event_id: int,
    last_event_id: int,
    emitted_chunk_text: str,
    counter: dict,
) -> tuple[int, int, str]:
    """on_chat_model_stream 实时 chunk 上行。

    委托 _emit_chunks(feed 分支)统一处理 event_id 自增 + send_json + chunk
    文本累积。把 event 级 event_id 当作 helper 内部自增的 seed,helper
    返回后把状态同步回局部变量。
    """
    chunk = event.get("data", {}).get("chunk")
    content = getattr(chunk, "content", "") if chunk else ""
    if not content:
        return event_id, last_event_id, emitted_chunk_text
    counter["event_id"] = event_id
    counter["last_event_id"] = last_event_id
    await _emit_chunks(websocket, parser, content, counter)
    return counter["event_id"], counter["last_event_id"], counter["emitted_chunk_text"]


async def _emit_chat_model_end_fallback(
    websocket: WebSocket,
    parser: ThinkingParser,
    event: dict,
    event_id: int,
    last_event_id: int,
    emitted_chunk_text: str,
    counter: dict,
) -> tuple[int, int, str]:
    """on_chat_model_end 兜底:非流式 LLM 只发 end 不发 stream 时从这里拿全量。

    WHY 仅在 emitted_chunk_text 为空时兜底:避免与 stream 事件重复 emit —
    测试用 mock agent 会同时发 N 个 stream + 1 个 end 携带全量。
    """
    output = event.get("data", {}).get("output")
    end_content = getattr(output, "content", "") if output else ""
    if not (isinstance(end_content, str) and end_content and not emitted_chunk_text):
        return event_id, last_event_id, emitted_chunk_text
    counter["event_id"] = event_id
    counter["last_event_id"] = last_event_id
    await _emit_chunks(websocket, parser, end_content, counter)
    return counter["event_id"], counter["last_event_id"], counter["emitted_chunk_text"]


async def _handle_tool_start_event(
    websocket: WebSocket,
    session_id: str,
    event: dict,
    event_id: int,
    last_event_id: int,
    emitted_chunk_text: str,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None] | None:
    """on_tool_start 事件分发:clarify 工具 → 挂起;其它工具 → thinking 帧。

    Returns:
        ``None`` 表示继续流;非 None 表示挂起并返回(澄清挂起时填入
        ``(question, options)``,handle_websocket 据此跳过质量门 + 跳过 done)。
    """
    tool_name = event.get("name", "未知工具")
    tool_input = event.get("data", {}).get("input") or {}
    logger.info(
        "WS on_tool_start: session=%s tool=%s event_id=%s input=%s",
        session_id,
        tool_name,
        event_id,
        str(tool_input)[:200],
    )
    if tool_name != _CLARIFY_TOOL_NAME:
        await websocket.send_json(
            {
                "type": "thinking",
                "content": f"[调用工具] {tool_name}",
                "event_id": event_id,
            }
        )
        return None
    # === 澄清挂起 ===
    # LLM 决定追问用户:把工具入参(问题 + 候选项)作为 clarification_request
    # 帧发出,然后挂起本轮流——不发 final / done。用户回答通过新 turn 注
    # 入,LLM 看到 ask_user 历史 + 用户回答,继续原任务。
    question, options = _parse_clarify_tool_input(event)
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
        return None
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
    return last_event_id, emitted_chunk_text, False, (question, options), None


def _parse_clarify_tool_input(event: dict) -> tuple[str, list[str]]:
    """解析 ask_user 工具入参,返回 ``(question, options)``。

    LLM 既可能传纯字符串列表 ``["火锅","烧烤"]`` 也可能传字典列表
    ``[{key:"classic",label:"经典必玩",description:"..."}]``。前端只展示
    纯文本按钮,所以把字典规范化为 label 字符串 — 优先 label/content/text
    /value/name,都缺再 str() 兜底;空字符串 / 纯空白丢弃。
    """
    tool_input = event.get("data", {}).get("input") or {}
    question = str(tool_input.get("question", "")).strip()
    raw_options = tool_input.get("options") or []
    options: list[str] = []
    if not isinstance(raw_options, list):
        return question, options
    for opt in raw_options:
        label: str | None = None
        if isinstance(opt, str):
            label = opt if opt.strip() else None
        elif isinstance(opt, dict):
            for key in ("label", "content", "text", "value", "name"):
                v = opt.get(key)
                if isinstance(v, str) and v.strip():
                    label = v
                    break
            if label is None:
                key_field = opt.get("key")
                if isinstance(key_field, str) and key_field.strip():
                    label = key_field
        if label is None:
            continue
        options.append(label.strip())
        if len(options) >= 6:
            break
    return question, options


async def _handle_tool_end_event(
    websocket: WebSocket,
    session_id: str,
    event: dict,
    event_id: int,
) -> None:
    """on_tool_end 事件:发 thinking 帧(工具返回内容,截 100 字符)。"""
    tool_name = event.get("name", "未知工具")
    output = event.get("data", {}).get("output")
    logger.info(
        "WS on_tool_end: session=%s tool=%s event_id=%d output_chars=%d",
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


async def _handle_graph_interrupt(
    websocket: WebSocket,
    session_id: str,
    gi: Any,
    last_event_id: int,
    emitted_chunk_text: str,
) -> tuple[int, str, bool, tuple[str, list[str]] | None, tuple | None]:
    """GraphInterrupt 异常:发 confirmation_request 帧并挂起。

    WHY 理论路径:langgraph 0.6+ 实际在 _loop.__exit__ 主动 suppress,
    见 ``_drain_pending_hitl_interrupts`` fallback。
    """
    interrupts = gi.args[0] or ()  # GraphInterrupt(interrupts=[...])
    logger.info(
        "WS HITL GraphInterrupt 捕获: session=%s, interrupts=%d",
        session_id,
        len(interrupts),
    )
    last_event_id = await _emit_hitl_confirmation_frames(websocket, session_id, interrupts, last_event_id)
    pending: tuple | None = tuple(interrupts) if interrupts else None
    # WHY 不写 _session_hitl_state:挂起 interrupt 已经存到 checkpoint 的
    # ``__interrupt__`` channel,续流时通过 ``agent.aget_state(thread_id)``
    # 读回,无需进程内缓存(多 worker 部署天然兼容)。
    return last_event_id, emitted_chunk_text, False, None, pending


async def _drain_pending_hitl_interrupts(
    agent: Any,
    websocket: WebSocket,
    session_id: str,
    astream_kwargs: dict[str, Any],
    last_event_id: int,
    emitted_chunk_text: str,
) -> tuple[int, str, tuple | None]:
    """langgraph 0.6+:从 ``agent.aget_state(config).interrupts`` 读 pending interrupt。

    Pregel._loop.__exit__ 会主动 ``return True`` 抑制 GraphInterrupt(把
    interrupt 信息存到 checkpoint 的 ``__interrupt__`` channel),所以
    ``agent.astream_events`` 不抛异常而正常结束。HITL 状态只能从
    ``agent.get_state(config).interrupts`` 读取 — langgraph 0.6+ 暴露
    pending interrupt 的官方 API。

    WHY ``agent.aget_state``(不是 ``get_state``):agent 用 AsyncSqliteSaver
    时,``checkpointer.aget_tuple`` 是 async;同步 ``get_state`` 内部
    ``checkpointer.get_tuple(config)`` 在 AsyncSqliteSaver 上拿到的是
    coroutine(没 await),触发 "coroutine 'aget_tuple' was never awaited"
    warning,interrupts 永远空。

    Returns:
        ``(last_event_id, emitted_chunk_text, pending_interrupts_or_none)``:
        ``pending_interrupts_or_none`` 为 ``None`` 时表示无 HITL 挂起,继续
        主流程。
    """
    try:
        snapshot = await agent.aget_state(astream_kwargs["config"])
        pending_interrupts = tuple(snapshot.interrupts) if snapshot.interrupts else ()
    except Exception as gs_exc:  # noqa: BLE001 — 边界统一收口
        logger.warning("WS get_state 失败,跳过 HITL state 兜底: %s", gs_exc)
        pending_interrupts = ()
    if not pending_interrupts:
        return last_event_id, emitted_chunk_text, None
    logger.info(
        "WS HITL state.interrupts 捕获: session=%s, interrupts=%d",
        session_id,
        len(pending_interrupts),
    )
    last_event_id = await _emit_hitl_confirmation_frames(websocket, session_id, pending_interrupts, last_event_id)
    return last_event_id, emitted_chunk_text, pending_interrupts


async def _emit_hitl_confirmation_frames(
    websocket: WebSocket,
    session_id: str,
    interrupts: Any,
    last_event_id: int,
) -> int:
    """把 langgraph Interrupt 序列翻成 confirmation_request 帧。

    共用于 ``_handle_graph_interrupt`` 和 ``_drain_pending_hitl_interrupts``。
    挂起状态由 checkpoint 的 ``__interrupt__`` channel 持久化(多 worker
    部署天然兼容),不在进程内缓存。
    """
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
    return last_event_id


async def _finalize_stream(
    websocket: WebSocket,
    parser: ThinkingParser,
    counter: dict[str, Any],
    *,
    session_id: str,
    prompt: dict,
    agent: Any,
    stream_guard: StreamGuard,
    last_event_id: int,
) -> tuple[int, str, bool]:
    """astream 收尾:flush parser,emit token_usage / final / stats 帧。

    Returns:
        ``(last_event_id, response_text, stream_completed)``
    """
    # 正常结束:先 flush parser 残留内容,再发 token_usage → final → stats。
    # chunk / thinking 已在循环里实时送出,这里不再做 16 字符切碎 / re.findall。
    # response_text 给下游 add_message / 质量门使用,语义与旧版一致:
    # 剥离 <thinking> 标签后的纯回复文本。ThinkingParser 实时 emit 时已
    # 把 thinking 内容作为独立 thinking 帧送出,emitted_chunk_text 自然不含
    # 任何 thinking 标签,所以 response_text = emitted_chunk_text.strip()。
    response_text = ""

    # 流末 flush:parser 末尾留的 hold / 未闭合 thinking 块,作为兜底帧发出。
    # WHY 必须调:流式标签可能最后一刻才凑齐(比如 "<thinking>思考</th" 在
    # 最后 chunk 才凑完),parser 内部 hold 不发,flush 把残余 emit 出去。
    counter["event_id"] = last_event_id
    counter["last_event_id"] = last_event_id
    await _emit_chunks(websocket, parser, None, counter, flush=True)
    last_event_id = counter["last_event_id"]
    emitted_chunk_text = counter["emitted_chunk_text"]

    if emitted_chunk_text:
        response_text = emitted_chunk_text.strip()
        last_event_id = await _emit_token_usage_and_final(websocket, prompt, response_text, last_event_id)

    last_event_id = await _emit_stream_stats_frame(websocket, agent, stream_guard, last_event_id)
    return last_event_id, response_text, True


async def _emit_token_usage_and_final(
    websocket: WebSocket,
    prompt: dict,
    response_text: str,
    last_event_id: int,
) -> int:
    """流末发 token_usage + final 两帧,返回新 last_event_id。

    WHY 独立:final 帧格式固定,但 token_usage 涉及 ``_estimate_tokens`` 调
    用(走 count_tokens_approximately,与 deepagents 决策同源);抽出后
    ``_finalize_stream`` 只负责编排 flush → 收尾帧 → stats 三步,§1.2 可达。
    """
    # token_usage:估算 token + context 占用率。范围是 prompt["messages"]
    # + 本轮 assistant 响应 = 整个对话上下文(不只看本轮响应),这样 UI %
    # 才跟 deepagents 实际 trigger 决策用的 token 计数同源。
    # prompt 是 _run_agent_streaming 入参,自带 system 段 + 历史 + 本轮 user
    # 消息;这里再 append 一个 assistant 角色 dict 模拟刚生成的回复入库后
    # 的样子(下游 add_message 也是 assistant role,所以格式对齐)。
    full_context_messages: list[dict[str, Any]] = list(prompt["messages"]) + [
        {"role": "assistant", "content": response_text}
    ]
    estimated_tokens, context_usage = _estimate_tokens(full_context_messages, context_window=CONFIG["context_window"])
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

    # final 帧:用实时 emit 累积的 chunk 文本(已剥 thinking 标签)。
    # WHY 不在流期间发 final:旧实现在流末才发,前端 spinner 一直转;
    # 新实现 chunk 实时发,但 final 仅在结束时发一次,客户端据此停止
    # spinner 并把 chunks 拼成完整回复展示。
    final_event_id = last_event_id + 1
    await websocket.send_json(
        {
            "type": "final",
            "content": response_text,
            "event_id": final_event_id,
        }
    )
    return final_event_id


async def _emit_stream_stats_frame(
    websocket: WebSocket,
    agent: Any,
    stream_guard: StreamGuard,
    last_event_id: int,
) -> int:
    """发送 ``type=stats`` 元事件,返回新 last_event_id。

    顺序在 done 之前,确保 done 始终是流的最后一帧。错误路径不会发 stats
    (前面已 return),符合"错误即终止"语义。
    """
    stats_event_id = last_event_id + 1
    fallbacks_count = 0
    if hasattr(agent, "stats") and isinstance(agent.stats, dict):
        fallbacks_count = int(agent.stats.get("fallbacks", 0))
    await websocket.send_json(
        {
            "type": "stats",
            "content": "",
            "event_id": stats_event_id,
            "retries": int(stream_guard.stats.get("retries", 0)),
            "events_emitted": int(stream_guard.stats.get("events_emitted", 0)),
            "fallbacks": fallbacks_count,
        }
    )
    return stats_event_id
