"""StreamGuard 模块的测试。

该文件验证 `nexus.backend.resilience.stream_guard` 模块的核心契约：
  - happy path：每个事件附带单调递增的 `event_id`
  - 失败重试：可重试错误重试至成功；不 yield error 事件
  - 失败用尽：yield `type=error` 事件（带 `error_code` / `replay_from_event_id`），不抛
  - 不可重试错误（auth / bad_request / context_length）：直接 yield error，不重试
  - `replay_from_event_id` 反映"重试前已发出的事件数"
  - stats 准确累计 retries / events_emitted
  - kwargs 透传到底层 astream_events
  - TimeoutError 归为 TIMEOUT，可重试
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openai import (
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from nexus.backend.resilience.stream_guard import StreamGuard

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


def _bad_request_error(
    code: str = "invalid_value", message: str = "bad request"
) -> BadRequestError:
    """构造一个 OpenAI BadRequestError（400）。"""
    return BadRequestError(
        message,
        response=MagicMock(status_code=400),
        body={"error": {"message": message, "code": code}},
    )


# ---------------- happy path ----------------


async def test_happy_path_passes_through_with_event_ids() -> None:
    """无故障路径：每个 chunk 事件附带递增的 event_id，其它字段透传。"""
    counter = {"n": 0}

    async def astream(input, **kwargs):  # noqa: ARG001
        for i in range(3):
            counter["n"] += 1
            yield {"type": "chunk", "content": f"c{i}"}

    guard = StreamGuard(astream)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 3
    assert [e["event_id"] for e in events] == [1, 2, 3]
    assert all(e["type"] == "chunk" for e in events)
    assert [e["content"] for e in events] == ["c0", "c1", "c2"]
    # 内部 event_id 计数对齐
    assert counter["n"] == 3
    # 全部成功，stats 应无 retries
    assert guard.stats["retries"] == 0
    assert guard.stats["events_emitted"] == 3


# ---------------- retry-after-failure: 成功路径 ----------------


async def test_retry_after_rate_limit_then_success() -> None:
    """RateLimitError → 重试 → 第二次成功；不 yield error 事件。"""
    call_id = {"n": 0}

    async def astream_factory(input, **kwargs):  # noqa: ARG001
        current = call_id["n"]
        call_id["n"] += 1
        if current == 0:
            # 第一次：3 个 chunk 后抛 RateLimitError
            for i in range(3):
                yield {"type": "chunk", "content": f"first-{i}"}
            raise _rate_limit_error()
        # 第二次（重试）：3 个 chunk 正常完成
        for i in range(3):
            yield {"type": "chunk", "content": f"second-{i}"}

    guard = StreamGuard(astream_factory, max_total_retries=2)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    # 3 (first) + 3 (second) = 6 个 chunk，无 error 事件
    assert len(events) == 6
    assert all(e["type"] == "chunk" for e in events)
    assert [e["content"] for e in events] == [
        "first-0",
        "first-1",
        "first-2",
        "second-0",
        "second-1",
        "second-2",
    ]
    # 第一次 yield 的 event_id 是 1-3，第二次是 4-6（连续，因为是幂等重试）
    assert [e["event_id"] for e in events] == [1, 2, 3, 4, 5, 6]
    assert guard.stats["retries"] == 1
    # 上游被调了 2 次
    assert call_id["n"] == 2


# ---------------- retry-exhausted: 错误事件 ----------------


async def test_retry_exhausted_yields_error_event() -> None:
    """重试用尽 → yield error 事件（带 error_code=rate_limit_exhausted），不抛。"""
    call_id = {"n": 0}

    async def always_fails_after_first_chunk(input, **kwargs):  # noqa: ARG001
        call_id["n"] += 1
        yield {"type": "chunk", "content": "only"}
        raise _rate_limit_error()

    guard = StreamGuard(always_fails_after_first_chunk, max_total_retries=1)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    # max_total_retries=1 意味着总共 2 次（首次 + 1 重试）
    # 每次调用都 yield 1 chunk + raise 1 次
    # → 第 1 次：chunk(1) + raise → 重试
    # → 第 2 次：chunk(2) + raise → 用尽，yield error
    assert call_id["n"] == 2
    # 共 2 chunk + 1 error
    chunk_events = [e for e in events if e["type"] == "chunk"]
    error_events = [e for e in events if e["type"] == "error"]
    assert len(chunk_events) == 2
    assert len(error_events) == 1
    err = error_events[0]
    assert err["error_code"] == "rate_limit_exhausted"
    # replay_from_event_id 反映"重试前已发出的事件数"
    # 第二次失败时已发了 2 个事件
    assert err["replay_from_event_id"] == 2
    assert guard.stats["retries"] == 1


async def test_zero_retries_yields_error_after_first_failure() -> None:
    """max_total_retries=0 时不重试，直接 yield error。"""
    async def fails_after_2(input, **kwargs):  # noqa: ARG001
        yield {"type": "chunk", "content": "a"}
        yield {"type": "chunk", "content": "b"}
        raise _rate_limit_error()

    guard = StreamGuard(fails_after_2, max_total_retries=0)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 3  # 2 chunk + 1 error
    err = events[-1]
    assert err["type"] == "error"
    assert err["error_code"] == "rate_limit_exhausted"
    # error 事件本身的 event_id 是 3（紧跟 chunk 1, 2）
    assert err["event_id"] == 3
    # 重试前已发出 2 个 chunk
    assert err["replay_from_event_id"] == 2


# ---------------- 不可重试错误 ----------------


async def test_auth_error_does_not_retry() -> None:
    """AuthenticationError → 不重试，直接 yield error（auth）。"""
    call_id = {"n": 0}

    async def fails_with_auth(input, **kwargs):  # noqa: ARG001
        call_id["n"] += 1
        raise _auth_error()

    guard = StreamGuard(fails_with_auth, max_total_retries=5)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert call_id["n"] == 1  # 没重试
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["error_code"] == "auth"
    # auth 不可重试，没有"已重试次数"概念
    assert "message" in events[0]
    assert guard.stats["retries"] == 0


async def test_bad_request_does_not_retry() -> None:
    """BadRequestError（普通 400）→ 不重试，yield error（bad_request）。"""
    call_id = {"n": 0}

    async def fails_with_bad(input, **kwargs):  # noqa: ARG001
        call_id["n"] += 1
        raise _bad_request_error()

    guard = StreamGuard(fails_with_bad, max_total_retries=5)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert call_id["n"] == 1
    assert len(events) == 1
    assert events[0]["error_code"] == "bad_request"
    assert guard.stats["retries"] == 0


async def test_context_length_error_does_not_retry() -> None:
    """ContextLengthError → 不重试，yield error（context_length）。"""
    call_id = {"n": 0}

    async def fails_with_ctx(input, **kwargs):  # noqa: ARG001
        call_id["n"] += 1
        raise _bad_request_error(
            code="context_length_exceeded",
            message="context length exceeded",
        )

    guard = StreamGuard(fails_with_ctx, max_total_retries=5)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert call_id["n"] == 1
    assert len(events) == 1
    assert events[0]["error_code"] == "context_length"
    assert guard.stats["retries"] == 0


# ---------------- replay_from_event_id 语义 ----------------


async def test_replay_from_event_id_after_one_chunk() -> None:
    """只发了 1 个 chunk 后失败 → replay_from_event_id=1。"""
    async def fails_after_1(input, **kwargs):  # noqa: ARG001
        yield {"type": "chunk", "content": "a"}
        raise _rate_limit_error()

    guard = StreamGuard(fails_after_1, max_total_retries=0)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 2
    assert events[-1]["replay_from_event_id"] == 1


# ---------------- stats ----------------


async def test_stats_track_retries_and_events() -> None:
    """stats['retries'] 正确累计重试次数；stats['events_emitted'] 包括所有事件。"""
    call_id = {"n": 0}

    async def fails_twice_then_succeeds(input, **kwargs):  # noqa: ARG001
        current = call_id["n"]
        call_id["n"] += 1
        if current < 2:
            raise _rate_limit_error()
        for i in range(2):
            yield {"type": "chunk", "content": f"c{i}"}

    guard = StreamGuard(fails_twice_then_succeeds, max_total_retries=3)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert guard.stats["retries"] == 2
    # 两次失败都是 raise 之前没 yield chunk，所以 events_emitted 只有 2
    assert guard.stats["events_emitted"] == 2
    assert len(events) == 2
    # 上游被调了 3 次
    assert call_id["n"] == 3


async def test_stats_events_includes_error_event() -> None:
    """error 事件也计入 events_emitted。"""
    async def fails_immediately(input, **kwargs):  # noqa: ARG001
        raise _auth_error()

    guard = StreamGuard(fails_immediately, max_total_retries=0)
    async for _ in guard.astream_events({"x": 1}):
        pass

    assert guard.stats["events_emitted"] == 1  # 1 error event
    assert guard.stats["retries"] == 0


# ---------------- event_id 连续性 ----------------


async def test_event_ids_monotonically_increasing_across_retries() -> None:
    """event_id 单调递增，跨重试也连续（不重置）。"""
    call_id = {"n": 0}

    async def fail_once(input, **kwargs):  # noqa: ARG001
        current = call_id["n"]
        call_id["n"] += 1
        if current == 0:
            yield {"type": "chunk", "content": "first"}
            raise _rate_limit_error()
        for i in range(2):
            yield {"type": "chunk", "content": f"second-{i}"}

    guard = StreamGuard(fail_once, max_total_retries=1)
    ids = []
    async for ev in guard.astream_events({"x": 1}):
        ids.append(ev["event_id"])

    # 1 (first call) + 2 (retry) = 3 chunks, ids 应为 1, 2, 3
    assert ids == [1, 2, 3]


# ---------------- asyncio.TimeoutError / APITimeoutError ----------------


async def test_asyncio_timeout_is_classified_and_retried() -> None:
    """asyncio.TimeoutError 归为 LLMErrorKind.TIMEOUT，可重试。"""
    call_id = {"n": 0}

    async def timeout_then_succeed(input, **kwargs):  # noqa: ARG001
        current = call_id["n"]
        call_id["n"] += 1
        if current == 0:
            raise TimeoutError()
        yield {"type": "chunk", "content": "ok"}

    guard = StreamGuard(timeout_then_succeed, max_total_retries=2)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 1
    assert events[0]["type"] == "chunk"
    assert events[0]["content"] == "ok"
    assert guard.stats["retries"] == 1


async def test_api_timeout_error_is_classified_and_retried() -> None:
    """OpenAI APITimeoutError → TIMEOUT，可重试。"""
    call_id = {"n": 0}

    async def api_timeout_then_succeed(input, **kwargs):  # noqa: ARG001
        current = call_id["n"]
        call_id["n"] += 1
        if current == 0:
            raise APITimeoutError("request timeout")
        yield {"type": "chunk", "content": "ok"}

    guard = StreamGuard(api_timeout_then_succeed, max_total_retries=2)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 1
    assert events[0]["content"] == "ok"
    assert guard.stats["retries"] == 1


async def test_timeout_exhausted_yields_timeout_exhausted_error() -> None:
    """TIMEOUT 用尽 → yield error_code=timeout_exhausted。"""
    async def always_timeout(input, **kwargs):  # noqa: ARG001
        raise TimeoutError()

    guard = StreamGuard(always_timeout, max_total_retries=1)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["error_code"] == "timeout_exhausted"


# ---------------- kwargs 透传 ----------------


async def test_passes_through_kwargs() -> None:
    """kwargs 透传给底层 astream_events。"""
    received: dict = {}

    async def capture(input, **kwargs):  # noqa: ARG001
        received["input"] = input
        received.update(kwargs)
        yield {"type": "chunk", "content": "ok"}

    guard = StreamGuard(capture)
    async for _ in guard.astream_events(
        {"x": 1}, stream_mode="updates", config={"a": 1}
    ):
        pass

    assert received.get("input") == {"x": 1}
    assert received.get("stream_mode") == "updates"
    assert received.get("config") == {"a": 1}


async def test_input_passed_through() -> None:
    """input 参数透传到底层。"""
    received: dict = {}

    async def capture(input, **kwargs):  # noqa: ARG001
        received["input"] = input
        yield {"type": "chunk", "content": "ok"}

    guard = StreamGuard(capture)
    async for _ in guard.astream_events({"prompt": "hi"}):
        pass
    assert received["input"] == {"prompt": "hi"}


# ---------------- 上游 event 字段透传 ----------------


async def test_preserves_upstream_event_fields() -> None:
    """事件原 dict 字段全部保留，event_id 是新增字段，不修改其他字段。"""
    async def astream(input, **kwargs):  # noqa: ARG001
        yield {
            "type": "chunk",
            "content": "hello",
            "metadata": {"lang": "en"},
            "nested": {"a": 1, "b": [1, 2, 3]},
        }

    guard = StreamGuard(astream)
    events = []
    async for ev in guard.astream_events({"x": 1}):
        events.append(ev)

    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "chunk"
    assert ev["content"] == "hello"
    assert ev["metadata"] == {"lang": "en"}
    assert ev["nested"] == {"a": 1, "b": [1, 2, 3]}
    assert ev["event_id"] == 1


# ---------------- stats 拷贝隔离 ----------------


async def test_stats_returns_copy() -> None:
    """stats 属性返回 dict 拷贝，外部修改不影响内部状态。"""

    async def astream(input, **kwargs):  # noqa: ARG001
        yield {"type": "chunk"}

    guard = StreamGuard(astream)
    async for _ in guard.astream_events({"x": 1}):
        pass

    snap = guard.stats
    snap["retries"] = 999  # 篡改拷贝
    assert guard.stats["retries"] == 0  # 内部状态未变


# ---------------- 模块导出 ----------------


def test_module_exports_expected_symbols() -> None:
    """stream_guard 模块应导出 StreamGuard。"""
    import nexus.backend.resilience.stream_guard as sg_mod

    assert hasattr(sg_mod, "StreamGuard")
    assert callable(sg_mod.StreamGuard)


def test_stream_guard_default_retry_policy() -> None:
    """未传 retry_policy 时使用默认 RetryPolicy（不抛）。"""

    async def astream(input, **kwargs):  # noqa: ARG001
        yield {"type": "chunk"}

    guard = StreamGuard(astream)
    # 应能正常调用
    assert guard.stats == {"retries": 0, "fallbacks": 0, "events_emitted": 0}
