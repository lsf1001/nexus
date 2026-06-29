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
    """运行 agent 流式响应,把事件转发到 WebSocket。

    使用 :class:`StreamGuard` 包装 ``agent.astream_events``:
      - 给每个事件附加进程内单调递增的 ``event_id``
      - 可重试错误自动重试;不可重试 / 重试用尽 → yield 1 个 error 事件
      - 永不抛异常(StreamGuard 已保证),调用方不需要再 try/except
      - 检测到 LLM 调用 ``ask_user`` 工具时,发送 ``clarification_request``
        帧并挂起(不再发 final / done),用户回答通过新 turn 注入历史。
      - 检测到 ``GraphInterrupt``(langchain HITL 中断)时,发 ``confirmation_request``
        帧 + 把 ``pending_interrupts`` 填入返回值第 5 元组,handle_websocket 据此
        挂起本轮流,等客户端发 ``confirmation_response`` 后用 ``Command(resume=...)``
        新 astream 续流。

    Args:
        websocket: 目标 WebSocket 连接。
        session_id: 会话 ID(用于日志上下文 / HITL thread_id)。
        prompt: 已构建好的 prompt dict(含 ``messages``)。
        agent: 当前 Agent 实例(由 ``main.py`` 在调用时通过 ``get_agent()`` 注入)。
        resume_from_event_id: 客户端断点续传位置;Phase 1 简化模型下
            仅作为"客户端告知 server 上次看到哪",不做真正的去重过滤
            (每次流都有新的 event_id 序列)。
        command_resume: HITL 续流 payload(``{"decisions": [...]}``)。非空时
            跳过 messages 输入,改用 ``Command(resume=command_resume)`` 续流
            已挂起的图。

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

    # StreamGuard 包 astream_events;每次重试会重新调一次 astream_events
    # (幂等重试,由上游 LLM 自行决定是否真幂等)。
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
    had_error = False
    # 实时 chunk / thinking 分发器:每个 on_chat_model_stream 事件立即送进 parser,
    # 解析产出的 (kind, text) 帧立刻 send_json。ThinkingParser 同时识别
    # ``<thinking>...</thinking>`` 跨 chunk 标签分片,thinking 内容也实时送,
    # 不再缓存到流末做 re.findall。
    # WHY 2026-06-28:旧实现 ``full_response += content`` 把所有 chunk 攒到 LLM
    # 跑完才按 16 字符切碎发出,Agnes 慢模型场景前端 26 秒收不到任何帧,体感
    # "转圈"。改为实时 emit,前端每个 token 立即可见。
    parser = ThinkingParser()
    emitted_chunk_text = ""  # 累积已发 chunk 文本(供 final / DB 入库复用)

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
                # 不可重试 / 已耗尽:停止流(不再发 done)。
                # 返回空字符串,避免在错误路径下把 raw 文本(含 thinking 标签)写入 DB。
                if not retryable:
                    return last_event_id, "", False, None, None
                # 可重试但 StreamGuard 仍 yield error,意味着情况特殊
                # (理论上不会到这里,StreamGuard 内部就用尽了)。安全起见停止。
                return last_event_id, "", False, None, None

            # Phase 1 resume 过滤:跳过 event_id <= resume_from_event_id 的事件
            if resume_from_event_id is not None and event_id > 0 and event_id <= resume_from_event_id:
                last_event_id = max(last_event_id, event_id)
                continue

            # 业务事件转发
            if event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                content = getattr(chunk, "content", "") if chunk else ""
                if content:
                    # 实时发出:每个 chunk 立刻经 ThinkingParser 解析后 send_json,
                    # 不再缓存到流末 burst。Agnes 慢模型场景下,前端每个 token
                    # 立即可见,消除 26s 转圈体感。parser.feed 返回值是
                    # ``[(kind, text), ...]`` 列表,kinds ∈ {"chunk","thinking"}。
                    for kind, text in parser.feed(content):
                        event_id += 1
                        last_event_id = event_id
                        await websocket.send_json(
                            {
                                "type": kind,
                                "content": text,
                                "event_id": event_id,
                            }
                        )
                        if kind == "chunk":
                            emitted_chunk_text += text
            elif event_type == "on_chat_model_end":
                # 非流式 LLM(mock / 老式客户端)只发 end 不发 stream —
                # 此时 on_chat_model_stream 整个流里没有累积,需要从 end 拿全量
                # content 兜底,否则 reject 反思 / mock LLM 这类"一次性返回"的
                # 场景 emitted_chunk_text 始终为空,前端收不到任何 chunk/final。
                # WHY 仅在 emitted_chunk_text 为空时兜底:避免与 stream 事件重复
                # emit — 测试用 mock agent 会同时发 N 个 stream + 1 个 end
                # 携带全量,无脑合并会让前端看到同样的内容出现两次。
                output = event.get("data", {}).get("output")
                end_content = getattr(output, "content", "") if output else ""
                if isinstance(end_content, str) and end_content and not emitted_chunk_text:
                    for kind, text in parser.feed(end_content):
                        event_id += 1
                        last_event_id = event_id
                        await websocket.send_json(
                            {
                                "type": kind,
                                "content": text,
                                "event_id": event_id,
                            }
                        )
                        if kind == "chunk":
                            emitted_chunk_text += text
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
            # 其它事件(chain start/end、retriever、agent 节点等)→ 忽略,仅跟踪 event_id

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
        # 已经有 error 事件发出,StreamGuard 走完就不要再发 done
        return last_event_id, "", False, None, None

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
    for kind, text in parser.flush():
        event_id += 1
        last_event_id = event_id
        await websocket.send_json({"type": kind, "content": text, "event_id": event_id})
        if kind == "chunk":
            emitted_chunk_text += text

    if emitted_chunk_text:
        response_text = emitted_chunk_text.strip()

        # token_usage:估算 token + context 占用率
        # 范围:累积 prompt["messages"] + 本轮 assistant 响应 = 整个对话上下文,
        # 而不是只看本轮响应 —— UI 显示的 % 才跟 deepagents 实际 trigger
        # 决策用的 token 计数同源(都是 count_tokens_approximately)。
        # prompt 是 _run_agent_streaming 入参,自带 system 段 + 历史 + 本轮
        # user 消息;这里再 append 一个 assistant 角色 dict 模拟刚生成的回
        # 复入库后的样子(下游 add_message 也是 assistant role,所以格式对齐)。
        # 改用 emitted_chunk_text(不含 thinking 标签),与 DB 入库 / 质量门
        # raw_response 同源。
        full_context_messages: list[dict[str, Any]] = list(prompt["messages"]) + [
            {"role": "assistant", "content": response_text}
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
        last_event_id = final_event_id

    # 可观测:发送 ``type=stats`` 元事件,把本次流的 StreamGuard 统计
    # 暴露给前端。顺序在 done 之前,确保 done 始终是流的最后一帧。
    # 错误路径不会发 stats(前面已 return),符合"错误即终止"语义。
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
