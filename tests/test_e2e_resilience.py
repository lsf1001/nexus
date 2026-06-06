"""端到端韧性联调测试 + 可观测埋点测试。

Task 1.10：覆盖 Resilience 链路的 4 个端到端场景，并把 StreamGuard /
ResilientRunnable 的可观测计数（retries / fallbacks / events_emitted）
通过 ``type=stats`` 元事件暴露给前端。

覆盖场景：
  1. ``test_rate_limit_recovery_e2e``：
     上游前 2 次 429，第 3 次 200 → WS 全程不报错，最终收到完整 chunk 序列。
  2. ``test_fallback_to_secondary_model_e2e``：
     primary 持续 RateLimit + 有 fallback → 切到 fallback 成功，
     ``ResilientRunnable.stats['fallbacks'] >= 1``。
  3. ``test_resume_after_disconnect_e2e``：
     客户端发 ``resume`` 帧 + 合法 token → 服务端回 ``resume_ack``
     并携带正确 ``resume_from_event_id``（Phase 1 简化模型不做真正续传）。
  4. ``test_auth_error_no_retry_e2e``：
     上游 AuthenticationError（401）→ WS 收到 1 条 error 事件，
     ``error_code='auth'``，``retryable=False``，无 done 事件。

埋点校验：
  - ``test_stats_event_emitted_after_successful_stream``：流成功结束后
    WS 收到 ``type=stats`` 事件，含 ``retries`` / ``fallbacks`` /
    ``events_emitted`` 三个字段，且 ``retries`` >= 0。

注意事项：
  - 所有测试都 mock ``nexus.backend.main._agent``，不调真实 LLM。
  - 测试用 ``monkeypatch`` 注入 ws_token 和 resume_secret。
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
    """注入 ws_token + resume_secret，返回一个合法 token。"""
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    monkeypatch.setitem(config_module.CONFIG, "resume_secret", "test-resume-secret-xyz")
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


def _drain_after_done(ws, max_events: int = 10) -> list[dict]:
    """收完 done 之后继续收几个事件（用于拿 stats / resume_token）。"""
    extras: list[dict] = []
    for _ in range(max_events):
        try:
            msg = ws.receive_json()
        except Exception:
            break
        extras.append(msg)
        if msg.get("type") in {"resume_token", "stats"}:
            break
    return extras


def _make_streaming_mock(agent_factory) -> MagicMock:
    """构造一个可注入 astream_events 的 agent MagicMock，stats 提供 dict。"""
    mock_agent = MagicMock()
    mock_agent.astream_events = agent_factory
    mock_agent.stats = {"fallbacks": 0, "retries": 0}
    return mock_agent


# ============================================================
# 场景 1：rate_limit → 重试 → 成功
# ============================================================


def test_rate_limit_recovery_e2e(monkeypatch) -> None:
    """mock 上游前 2 次 429，第 3 次 200 → WS 全程不报错，收到完整 chunks。

    验证：
      - 没有 error 事件
      - 收到至少 1 个 chunk 事件
      - 收到 done 事件
      - 收到 stats 事件（含 retries > 0）
    """
    _authed_token(monkeypatch)

    call_count = {"n": 0}

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        current = call_count["n"]
        call_count["n"] += 1
        if current < 2:
            # 前 2 次：先 yield 1 个 chunk，再抛 429 → StreamGuard 重试
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content=f"try-{current}-")}}
            raise _rate_limit_error()
        # 第 3 次：成功
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="success-1")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="success-2")}}

    with TestClient(app) as client:
        # ``_make_streaming_mock`` 同时提供 astream_events + stats dict，
        # 方便后续 stats 事件读取 fallbacks。
        with patch("nexus.backend.main._agent", _make_streaming_mock(astream_events_factory)):
            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "rl-recovery-test"})

                events = _collect_until_done(ws)
                extras = _drain_after_done(ws, max_events=5)
                events.extend(extras)

                # 1) 无 error 事件
                errors = [e for e in events if e.get("type") == "error"]
                assert errors == [], f"应有 0 条 error，实际: {errors}"

                # 2) 至少 1 个 chunk
                chunks = [e for e in events if e.get("type") == "chunk"]
                assert len(chunks) >= 1, f"应至少 1 个 chunk，实际: {chunks}"

                # 3) 收到 done
                done_events = [e for e in events if e.get("type") == "done"]
                assert len(done_events) == 1, f"应恰好 1 个 done，实际: {done_events}"

                # 4) 收到 stats 事件，retries 至少 1（前 2 次失败后 2 次重试）
                stats_events = [e for e in events if e.get("type") == "stats"]
                assert len(stats_events) == 1, f"应恰好 1 个 stats，实际: {stats_events}"
                stats = stats_events[0]
                assert stats.get("retries", 0) >= 1, f"retries 应 >= 1，实际: {stats}"
                assert "fallbacks" in stats
                assert stats.get("fallbacks", -1) == 0
                assert "events_emitted" in stats
                assert stats.get("events_emitted", 0) >= 1

                # 5) StreamGuard 实际被调 3 次（前 2 次失败 + 第 3 次成功）
                assert call_count["n"] == 3

                # 6) stats 事件在 done 之前
                assert events.index(stats) < events.index(done_events[0])


# ============================================================
# 场景 2：fallback 切到 secondary
# ============================================================


async def test_fallback_to_secondary_model_e2e(monkeypatch) -> None:
    """primary 持续 RateLimit + 有 fallback → 切到 fallback 成功。

    验证 ``ResilientRunnable.stats['fallbacks'] >= 1``。

    实现说明：
      - WS 层的 fallback 取决于 ResilientRunnable 暴露的 astream 行为。
        而 main.py 直接调 ``agent.astream_events``，未走 ResilientRunnable
        的 ainvoke 重试/降级逻辑；因此本测试分两部分：
        (a) 单元层：验证 ResilientRunnable 的 ainvoke 在 primary 持续
            RateLimit 时切到 fallback 并累加 ``stats['fallbacks']``。
        (b) WS 集成层：把 mock agent.stats 设置为 ``{"fallbacks": 1, ...}``，
            验证 WS 端会把 fallbacks 字段透传到 ``type=stats`` 事件。
    """
    _authed_token(monkeypatch)

    # (a) 单元层验证 ResilientRunnable 的 fallback 计数
    from typing import Any

    from nexus.backend.llm.policies import RetryPolicy
    from nexus.backend.llm.wrapper import ResilientRunnable

    async def _primary_always_fails(_: Any) -> Any:
        raise _rate_limit_error()

    async def _fallback_succeeds(_: Any) -> Any:
        return "fallback_response"

    primary = MagicMock()
    primary._llm_type = "openai"
    primary.ainvoke = _primary_always_fails

    fallback = MagicMock()
    fallback._llm_type = "openai"
    fallback.ainvoke = _fallback_succeeds

    resilient = ResilientRunnable(
        primary=primary,
        fallback=fallback,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.001),
    )
    result = await resilient.ainvoke({"input": "test"})
    assert result == "fallback_response"
    # 关键断言：stats['fallbacks'] 被累加 >= 1
    assert resilient.stats["fallbacks"] >= 1, (
        f"fallbacks 应 >= 1，实际: {resilient.stats['fallbacks']}"
    )

    # (b) WS 集成层验证 stats 事件透传 fallbacks 字段
    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}

    # 让 mock agent 的 stats 反映 (a) 的结果
    mock_agent = _make_streaming_mock(astream_events_factory)
    mock_agent.stats = dict(resilient.stats)  # {"fallbacks": 1, "retries": 1}

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent", mock_agent):
            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "fallback-test"})

                events = _collect_until_done(ws)
                extras = _drain_after_done(ws, max_events=5)
                events.extend(extras)

                stats_events = [e for e in events if e.get("type") == "stats"]
                assert len(stats_events) == 1
                stats = stats_events[0]
                # fallbacks 字段应 >= 1（来自 (a) 的统计）
                assert stats.get("fallbacks", 0) >= 1, (
                    f"stats 事件 fallbacks 应 >= 1，实际: {stats}"
                )


# ============================================================
# 场景 3：resume 帧 + 合法 token
# ============================================================


def test_resume_after_disconnect_e2e(monkeypatch) -> None:
    """客户端发 resume 帧 + 合法 token → 服务端回 resume_ack，event_id 正确。

    Phase 1 简化模型：DeepAgents 状态不可续传，本测试只验证 token 校验 +
    服务端回 resume_ack，不做真正续传。
    """
    _authed_token(monkeypatch)

    token = make_token("test-session", 7, ttl_seconds=60)

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws?token=test-token") as ws:
            ws.send_json(
                {
                    "type": "resume",
                    "session_id": "test-session",
                    "resume_token": token,
                }
            )
            msg = ws.receive_json()
            assert msg.get("type") == "resume_ack"
            assert msg.get("session_id") == "test-session"
            assert msg.get("resume_from_event_id") == 7


# ============================================================
# 场景 4：auth 不可重试 → 1 条 error 事件
# ============================================================


def test_auth_error_no_retry_e2e(monkeypatch) -> None:
    """401 → WS 收到 1 条 error 事件，error_code=auth，retryable=False，无 done。

    验证：
      - 恰好 1 条 error 事件
      - error_code == 'auth'
      - retryable == False
      - 没有 done 事件
      - 没有 stats 事件（错误路径不发 stats）
    """
    _authed_token(monkeypatch)

    async def astream_with_auth(input, **kwargs):  # noqa: ARG001
        raise _auth_error()
        yield  # 让它成为 async generator

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent", _make_streaming_mock(astream_with_auth)):
            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "auth-test"})

                events = _collect_until_done(ws)

                # 1) 恰好 1 条 error
                errors = [e for e in events if e.get("type") == "error"]
                assert len(errors) == 1, f"应恰好 1 条 error，实际: {errors}"
                err = errors[0]
                assert err["error_code"] == "auth"
                assert err.get("retryable") is False
                assert "event_id" in err

                # 2) 没有 done（错误路径）
                done_events = [e for e in events if e.get("type") == "done"]
                assert done_events == [], f"错误路径不应有 done，实际: {done_events}"

                # 3) 没有 stats 事件（错误路径不发 stats）
                stats_events = [e for e in events if e.get("type") == "stats"]
                assert stats_events == [], f"错误路径不应有 stats，实际: {stats_events}"


# ============================================================
# 埋点：stats 事件字段完整性
# ============================================================


def test_stats_event_emitted_after_successful_stream(monkeypatch) -> None:
    """流成功结束后，WS 收到 ``type=stats`` 事件，含 retries / fallbacks / events_emitted。

    这是 stats 事件契约的回归测试：保证后端 wire 协议与前端 StreamEvent 类型对齐。
    """
    _authed_token(monkeypatch)

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        # 3 个 chunk，让 events_emitted > 0
        for i in range(3):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content=f"c{i}")}}

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent", _make_streaming_mock(astream_factory)):
            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "hello", "title": "stats-test"})

                events = _collect_until_done(ws)
                extras = _drain_after_done(ws, max_events=5)
                events.extend(extras)

                stats_events = [e for e in events if e.get("type") == "stats"]
                assert len(stats_events) == 1
                stats = stats_events[0]

                # 字段完整性
                assert "retries" in stats
                assert "fallbacks" in stats
                assert "events_emitted" in stats
                # 全部为 int
                assert isinstance(stats["retries"], int)
                assert isinstance(stats["fallbacks"], int)
                assert isinstance(stats["events_emitted"], int)
                # events_emitted 至少 1（流成功结束至少发了 done 之前的事件）
                assert stats["events_emitted"] >= 1
                # 成功路径 retries=0
                assert stats["retries"] == 0
                # fallbacks=0（mock agent 没有触发 fallback）
                assert stats["fallbacks"] == 0

                # stats 在 done 之前
                done_events = [e for e in events if e.get("type") == "done"]
                assert len(done_events) == 1
                assert events.index(stats) < events.index(done_events[0])

                # event_id 单调递增
                stats_id = stats["event_id"]
                done_id = done_events[0]["event_id"]
                assert isinstance(stats_id, int)
                assert isinstance(done_id, int)
                assert stats_id < done_id
