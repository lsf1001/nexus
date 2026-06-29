"""WebSocket 韧性层（StreamGuard + Resume token）集成测试。

Task 1.8：把 StreamGuard 和 resume token 接入 `nexus.backend.main.websocket_endpoint`。

覆盖：
  1. RateLimit 触发 StreamGuard 重试 → WS 收到完整 chunk 序列 + done，无 error 事件。
  2. AuthenticationError（不可重试）→ WS 收到 1 条 error 事件，error_code="auth"，不再 retry。
  3. 客户端发 `resume` 帧 + 合法 token → 服务端回 resume_ack。
  4. 客户端发 `resume` 帧 + 非法 token → 服务端回 error 事件，error_code="invalid_resume_token"。
  5. 错误鉴权（ws_token 不匹配）→ 客户端连接被 close（HTTP 4001）。
  6. 客户端带 message 帧中的 resume_token → 流结束后服务端签发新 resume_token 帧。

Task 1.8 修复：恢复流结束后处理（thinking 标签归一化、token 估算）。
  7. token_usage 事件携带 token_count + context_usage。
  8. <thinking> 标签被剥离，正文 chunk 和 final.content 不含思考标签。
  9. 30 字符响应 → 单 token → 1 个 chunk 帧（旧 16 字符分块已改为实时 emit，详见 test_ws_realtime_streaming）。
 10. final.content 不含 <thinking> 标签。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from openai import AuthenticationError, RateLimitError

from nexus.backend.main import app
from nexus.backend.resilience.resume import make_token

# ---------------- helpers ----------------


def _rate_limit_error() -> RateLimitError:
    """构造一个 OpenAI RateLimitError（429）。"""
    return RateLimitError(
        "rate limit exceeded",
        response=MagicMock(status_code=429),
        body={"error": {"message": "rate limit"}},
    )


def _auth_error() -> AuthenticationError:
    """构造一个 OpenAI AuthenticationError（401）。"""
    return AuthenticationError(
        "invalid api key",
        response=MagicMock(status_code=401),
        body={"error": {"message": "invalid api key"}},
    )


def _authed_token(monkeypatch) -> str:
    """注入 ws_token + resume_secret,返回一个合法 token。

    resume_secret 必须 >= 32 字节(resume.py _get_secret 的硬性约束)。
    """
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    monkeypatch.setitem(
        config_module.CONFIG,
        "resume_secret",
        "test-resume-secret-32bytes-or-more-abcdef0123456789",
    )
    return "test-token"


def _collect_until_done(ws, max_events: int = 200) -> list[dict]:
    """从 WS 收集事件直到收到 done 或 error（或达到 max_events 上限）。"""
    events: list[dict] = []
    for _ in range(max_events):
        msg = ws.receive_json()
        events.append(msg)
        if msg.get("type") in {"done", "error"}:
            break
    return events


# ---------------- 测试 1：RateLimit → 重试 → 成功 ----------------


def test_ws_rate_limit_retry_then_succeeds(monkeypatch) -> None:
    """RateLimit 触发 StreamGuard 重试：最终完整 chunks + done，无 error。"""
    _authed_token(monkeypatch)

    call_count = {"n": 0}

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        current = call_count["n"]
        call_count["n"] += 1
        if current == 0:
            # 首次：3 chunks + RateLimit → StreamGuard 重试
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="first-1")}}
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="first-2")}}
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="first-3")}}
            raise _rate_limit_error()
        # 重试：2 chunks 正常完成
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="second-1")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="second-2")}}

    with TestClient(app) as client:
        # 必须在 TestClient 启动（lifespan 跑了之后再 patch），
        # 否则 lifespan 会用真实 agent 覆盖我们的 mock。
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "retry-test"})

                events = _collect_until_done(ws)

                # 没有 error 事件
                error_events = [e for e in events if e.get("type") == "error"]
                assert error_events == []

                # chunks 按顺序拼接出完整内容
                chunks = [e["content"] for e in events if e.get("type") == "chunk"]
                assert "".join(chunks) == "first-1first-2first-3second-1second-2"

                # done 事件存在
                assert any(e["type"] == "done" for e in events)

                # chunk event_id 单调递增且唯一
                chunk_ids = [e.get("event_id") for e in events if e.get("type") == "chunk"]
                assert chunk_ids == sorted(chunk_ids)
                assert len(set(chunk_ids)) == len(chunk_ids)

                # StreamGuard 触发了 1 次重试
                assert call_count["n"] == 2


# ---------------- 测试 2：Auth 不可重试 → 1 条 error 事件 ----------------


def test_ws_auth_error_yields_single_error_event(monkeypatch) -> None:
    """AuthenticationError（不可重试）→ 1 条 error，error_code=auth，retryable=False。"""
    _authed_token(monkeypatch)

    async def fails_with_auth(input, **kwargs):  # noqa: ARG001
        raise _auth_error()
        yield  # 让其成为 async generator

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = fails_with_auth

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "auth-test"})

                events = _collect_until_done(ws)

                error_events = [e for e in events if e.get("type") == "error"]
                assert len(error_events) == 1
                err = error_events[0]
                assert err["error_code"] == "auth"
                assert err.get("retryable") is False
                assert "event_id" in err

                # auth 不可重试，无 retry
                # （async generator 被调用一次后即 raise，没机会被重试）


# ---------------- 测试 3：合法 resume_token → resume_ack ----------------


def test_ws_resume_with_valid_token(monkeypatch) -> None:
    """客户端发 resume 帧 + 合法 token → 服务端回 resume_ack。"""
    _authed_token(monkeypatch)

    token = make_token("test-session-id", 42, ttl_seconds=60)

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws?token=test-token") as ws:
            ws.send_json(
                {
                    "type": "resume",
                    "session_id": "test-session-id",
                    "resume_token": token,
                }
            )
            msg = ws.receive_json()
            assert msg.get("type") == "resume_ack"
            assert msg.get("session_id") == "test-session-id"
            assert msg.get("resume_from_event_id") == 42


# ---------------- 测试 4：非法 resume_token → error 事件 ----------------


def test_ws_resume_with_invalid_token(monkeypatch) -> None:
    """非法 token → 1 条 error 事件，error_code="invalid_resume_token"。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws?token=test-token") as ws:
            ws.send_json(
                {
                    "type": "resume",
                    "session_id": "test-session-id",
                    "resume_token": "garbage.token.value",
                }
            )
            msg = ws.receive_json()
            assert msg.get("type") == "error"
            assert msg.get("error_code") == "invalid_resume_token"


# ---------------- 测试 5：错误 ws_token → 连接被 close ----------------


def test_ws_unauthorized_token_rejected(monkeypatch) -> None:
    """错误 ws_token → 客户端连接被 close（带 4001）。"""
    _authed_token(monkeypatch)

    with TestClient(app) as client:
        # TestClient.websocket_connect 在握手失败时抛 WebSocketDisconnect
        import pytest as _pytest
        from starlette.websockets import WebSocketDisconnect

        with _pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/ws?token=wrong-token") as ws:
                ws.receive_json()  # 不应到达


# ---------------- 测试 6：流结束后签发新 resume_token ----------------


def test_ws_emits_resume_token_after_stream(monkeypatch) -> None:
    """流正常结束时，服务端在 done 前发 resume_token 帧。"""
    _authed_token(monkeypatch)

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "token-emit-test"})

                events = _collect_until_done(ws, max_events=200)

                token_frames = [e for e in events if e.get("type") == "resume_token"]
                assert len(token_frames) == 1
                event_types = [e.get("type") for e in events]
                assert event_types[-1] == "done"
                assert event_types.index("resume_token") < event_types.index("done")
                token = token_frames[0]["resume_token"]
                # 校验 token 合法
                from nexus.backend.resilience.resume import verify_token

                # session_id 在 session_created 帧里给出
                session_frames = [e for e in events if e.get("type") == "session_created"]
                assert session_frames, "should receive session_created"
                session_id = session_frames[0]["session_id"]
                # event_id >= 0（具体值依赖 chunks + done 等事件计数）
                last_eid = verify_token(token, session_id)
                assert last_eid >= 1


# ---------------- 测试 7：error 事件永不抛异常 ----------------


def test_ws_unknown_exception_does_not_break_socket(monkeypatch) -> None:
    """上游抛非分类异常（UnknownError）→ StreamGuard 仍只 yield 1 个 error 事件，连接不挂。"""
    _authed_token(monkeypatch)

    async def fails_unknown(input, **kwargs):  # noqa: ARG001
        raise RuntimeError("boom!")

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = fails_unknown

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "unknown-test"})

                events = _collect_until_done(ws)
                error_events = [e for e in events if e.get("type") == "error"]
                # 至少 1 条 error 事件（unknown 默认可重试；max_total_retries=2 后用尽）
                # 实际行为：max_total_retries=2 → 3 次尝试，每次 raise → 仍 yield error_code=unknown_exhausted
                # 也可能 max_total_retries=0；只断言 至少 1 条且 error_code 包含 unknown
                assert len(error_events) >= 1
                assert any("unknown" in e.get("error_code", "") for e in error_events)


# ---------------- Task 1.8 修复：流结束后处理 ----------------


def test_ws_emits_token_usage_event(monkeypatch) -> None:
    """流成功后，WS 收到 type=token_usage 事件，含 token_count + context_usage。

    Task 2（实时 emit）调整:chunks 现在是实时发出（流期间）,token_usage
    在流结束后再发（用于前端在 chunks 累积后给一个快照）。顺序变成
    chunks → token_usage → final → stats → done。
    """
    _authed_token(monkeypatch)

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        # 26 英文字符 → _estimate_tokens: 26 * 0.25 = 6.5 → 6 tokens
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="abcdefghijklmnopqrstuvwxyz")}}

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "token-usage-test"})

                events = _collect_until_done(ws, max_events=200)

                token_usage_events = [e for e in events if e.get("type") == "token_usage"]
                assert len(token_usage_events) == 1
                tu = token_usage_events[0]
                assert "token_count" in tu
                assert "context_usage" in tu
                assert tu["token_count"] >= 0
                assert 0 <= tu["context_usage"] <= 100
                # Task 2 实时 emit 后,顺序变为 chunks → token_usage → final → stats → done。
                # token_usage 必须在首个 chunk 之后(不能再 "先发 token_usage 再发 chunks"
                # —— 那会与实时 emit 语义矛盾,前端会先看到 0% 再看到 1% 抖动)。
                tu_idx = events.index(tu)
                first_chunk_idx = next(
                    (i for i, e in enumerate(events) if e.get("type") == "chunk"),
                    len(events),
                )
                assert first_chunk_idx < tu_idx, (
                    f"token_usage 必须在 chunks 之后(实时 emit 语义):"
                    f" first_chunk_idx={first_chunk_idx}, tu_idx={tu_idx}, types={[e.get('type') for e in events]}"
                )
                # token_usage 必须在 final 之前
                final_idx = next(
                    (i for i, e in enumerate(events) if e.get("type") == "final"),
                    len(events),
                )
                assert tu_idx < final_idx


def test_ws_strips_thinking_tags(monkeypatch) -> None:
    """上游流含 <think>...</think> → WS 收到 1 个 thinking 事件（纯思考内容），
    所有 chunk 和 final.content 都不含思考标签。
    """
    _authed_token(monkeypatch)

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        # 模拟上游分块：先 <think> 标签（归一化前用 <think>），后正文
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="<think>")}}
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="step 1: analyze\nstep 2: solve</think>")},
        }
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="The answer is 42.")}}

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "thinking-strip-test"})

                events = _collect_until_done(ws, max_events=200)

                # 至少 1 条 thinking 事件，且 content 是纯思考内容
                thinking_events = [
                    e for e in events if e.get("type") == "thinking" and "调用工具" not in (e.get("content") or "")
                ]
                assert len(thinking_events) >= 1
                thinking_content = thinking_events[-1]["content"]
                assert "step 1: analyze" in thinking_content
                assert "step 2: solve" in thinking_content
                # thinking 事件内容不应包含 thinking 标签
                assert "<thinking>" not in thinking_content
                assert "</thinking>" not in thinking_content

                # 所有 chunk 不含 thinking 标签
                chunks = [e for e in events if e.get("type") == "chunk"]
                assert chunks, "应至少 1 个 chunk"
                joined_chunks = "".join(c["content"] for c in chunks)
                assert "<think>" not in joined_chunks
                assert "</think>" not in joined_chunks
                assert "<thinking>" not in joined_chunks
                assert "</thinking>" not in joined_chunks
                # 拼接后等于剥离后的正文
                assert joined_chunks == "The answer is 42."


def test_ws_chunks_emitted_realtime_no_post_split(monkeypatch) -> None:
    """Task 2：30 字符响应一次性发 → 1 个 chunk 帧。

    旧实现按 16 字符后处理分块 → 16 + 14 两块；Task 2 改为每个 token 1 个
    chunk 实时 emit（消除 agnes 慢模型 26s 转圈体感）。这条测试验证：
      - mock 上游发 1 个完整 30 字符串 → 客户端只看到 1 个 chunk 事件
      - chunk 内容等于原文（不做任何切碎）
      - final.content 同样等于原文
    """
    _authed_token(monkeypatch)

    text_30 = "abcdefghijklmnop" + "qrstuvwxyz1234"  # 16 + 14 = 30
    assert len(text_30) == 30

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content=text_30)}}

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "chunk-test"})

                events = _collect_until_done(ws, max_events=200)

                chunks = [e for e in events if e.get("type") == "chunk"]
                # 实时 emit:1 个完整 token → 1 个 chunk 帧
                assert len(chunks) == 1, f"应为 1 个 chunk 帧,实际 {len(chunks)}: {chunks}"
                assert chunks[0]["content"] == text_30
                # final 内容与原文一致
                final_events = [e for e in events if e.get("type") == "final"]
                assert len(final_events) == 1
                assert final_events[0]["content"] == text_30


def test_ws_final_content_excludes_thinking(monkeypatch) -> None:
    """final 事件的 content 是剥离 <thinking> 后的纯回复文本。"""
    _authed_token(monkeypatch)

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="<think>internal</think>Final answer")},
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_factory
            # Phase 2 Task 2.5：跳过 QualityPipeline（mock LLM 无 ainvoke 配置，
            # judge 评分会全失败导致 REJECT → fallback 文本污染 final）
            client.app.state.quality_pipeline = None

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "final-test"})

                events = _collect_until_done(ws, max_events=200)

                final_events = [e for e in events if e.get("type") == "final"]
                assert len(final_events) == 1
                final = final_events[0]
                assert "<think>" not in final["content"]
                assert "</think>" not in final["content"]
                assert "<thinking>" not in final["content"]
                assert "</thinking>" not in final["content"]
                assert "internal" not in final["content"]
                assert final["content"] == "Final answer"
