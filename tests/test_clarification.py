"""澄清流程（ask_user 工具 → clarification_request 帧）测试。

覆盖三类路径:
  1. 正常:LLM 调 ask_user 工具 → ws 收到 clarification_request + 没 done/final,
     会话历史追加 [澄清中] 占位条目(供下一 turn 的 LLM 看到上下文)。
  2. 工具入参异常(没有 question):降级为普通工具调用,正常流走完。
  3. JSONDecodeError 韧性:发非 JSON 帧后 ws 不挂,后续正常 JSON 仍能处理。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from nexus.backend.main import app


def _authed_token(monkeypatch) -> str:
    from nexus.backend import config as config_module

    monkeypatch.setitem(config_module.CONFIG, "ws_token", "test-token")
    monkeypatch.setitem(config_module.CONFIG, "resume_secret", "test-resume-secret-xyz")
    return "test-token"


# ============== 1. 正常:ask_user 触发 clarification_request ==============


def test_ask_user_tool_triggers_clarification_request(monkeypatch) -> None:
    """LLM 调 ask_user 工具 → 客户端收到 clarification_request,没 final/done。"""
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        # 模拟 LLM 决定追问,工具入参含 question + options
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "question": "今天想吃什么?",
                    "options": ["火锅", "烧烤", "随便"],
                }
            },
        }
        # on_tool_end 不应到达 —— _run_agent_streaming 在 ask_user 触发时就
        # return 了。astream_events 立刻 close generator 也行,这里留空。

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "午饭", "title": "clarify-test"})

                # 收到 clarification_request 后服务端不发送 done/final,
                # 因此 _collect_until_done 会因 timeout 阻塞;改用 N 次循环
                # 收集所有帧(只要收到 clarification_request 就 break)。
                events: list[dict] = []
                for _ in range(20):
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    events.append(msg)
                    if msg.get("type") == "clarification_request":
                        break

    # 关键断言 1:收到 clarification_request 帧
    clarify_events = [e for e in events if e.get("type") == "clarification_request"]
    assert len(clarify_events) == 1
    clarify = clarify_events[0]
    assert clarify["content"] == "今天想吃什么?"
    assert clarify["options"] == ["火锅", "烧烤", "随便"]

    # 关键断言 2:本轮没 final / done / error(LLM 追问时不算本轮完成)
    assert not any(e.get("type") in {"final", "done", "error"} for e in events)


def test_ask_user_empty_options_lets_user_free_input(monkeypatch) -> None:
    """ask_user 工具入参 options=None / [] → 客户端收到空 options,允许自由输入。"""
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "question": "你能再说清楚点吗?",
                    "options": None,
                }
            },
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "模糊指令", "title": "clarify-free"})

                events: list[dict] = []
                for _ in range(20):
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    events.append(msg)
                    if msg.get("type") == "clarification_request":
                        break

    clarify = next(e for e in events if e.get("type") == "clarification_request")
    assert clarify["content"] == "你能再说清楚点吗?"
    assert clarify["options"] == []  # 空 list,前端走自由输入分支


# ============== 2. 工具入参异常:缺 question → 降级 ==============


def test_ask_user_without_question_falls_back(monkeypatch) -> None:
    """ask_user 工具入参缺 question(LLM 出错)→ 降级为普通工具,正常流走完。"""
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        # 异常入参:只有 options 没 question
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "options": ["A", "B"],
                    # question 字段缺失
                }
            },
        }
        # on_tool_end 必须 yield 才能让 LLM 流程走完 —— 真实场景里异常入参
        # 通常会被 on_tool_end 接住,我们手动 yield 一下让流正常 close
        yield {
            "event": "on_tool_end",
            "name": "ask_user",
            "data": {"output": "[ask_user] 降级"},
        }
        # 然后 LLM 给出正常回复
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="fallback reply")},
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "test", "title": "fallback-test"})

                events: list[dict] = []
                for _ in range(20):
                    msg = ws.receive_json()
                    events.append(msg)
                    if msg.get("type") == "done":
                        break

    # 关键断言:没 clarification_request 帧(降级了)
    assert not any(e.get("type") == "clarification_request" for e in events)
    # 关键断言:有 done 帧(流走完了)
    assert any(e.get("type") == "done" for e in events)
    # 关键断言:有 thinking 帧表示 "调用工具 ask_user"(降级分支)
    tool_thinking = [e for e in events if e.get("type") == "thinking" and "ask_user" in (e.get("content") or "")]
    assert len(tool_thinking) >= 1


# ============== 3. JSONDecodeError 韧性(ws.py 内层 try 修复) ==============


def test_ws_does_not_close_on_non_json_frame(monkeypatch) -> None:
    """客户端发非 JSON 帧(空字符串 / 心跳 ping)→ ws 不挂,后续正常 JSON 仍能处理。

    修复前的 bug:JSONDecodeError 在外层 except,handler 整体退出,等价 ws 关闭,
    客户端重连后又被下一个 ping 杀掉,死循环。
    修复后:内层 try 单独接住,continue 重新 receive,handler 不退出。
    """
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="ok")},
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                # 1) 发空字符串(非 JSON)
                ws.send_text("")
                # 2) 发垃圾
                ws.send_text("not-json{")
                # 3) 再发一条正常消息 → 应该能正常收到 reply
                ws.send_json({"content": "hello after garbage", "title": "recovery"})

                events: list[dict] = []
                for _ in range(20):
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    events.append(msg)
                    if msg.get("type") == "done":
                        break

    # 关键断言:前两条非 JSON 帧不应让 ws 挂掉,第三条能正常得到回复
    chunks = [e["content"] for e in events if e.get("type") == "chunk"]
    assert "ok" in "".join(chunks), f"expected reply for recovery message, got: {events}"
    assert any(e.get("type") == "done" for e in events)


# ============== 4. ask_user 工具自身可被 invoke ==============


def test_ask_user_tool_basic_invoke() -> None:
    """ask_user 工具独立调用:返回占位说明 + 截断超长 options。"""
    from nexus.backend.tools import ask_user

    # 正常:有 question 和 options
    result = ask_user.invoke({"question": "几点开饭?", "options": ["6点", "7点"]})
    assert "几点开饭?" in result
    assert "6点" in result
    assert "7点" in result

    # options=None → 跳过 options 部分
    result_none = ask_user.invoke({"question": "为啥?", "options": None})
    assert "为啥?" in result_none
    assert "options=" not in result_none

    # options 超过 6 个 → 截断
    many = [f"选项{i}" for i in range(10)]
    result_many = ask_user.invoke({"question": "选哪个?", "options": many})
    for i in range(6):
        assert f"选项{i}" in result_many
    for i in range(6, 10):
        assert f"选项{i}" not in result_many

    # options 包含空字符串 / 纯空白 → 跳过
    result_mixed = ask_user.invoke({"question": "q?", "options": ["A", "", "  ", "B"]})
    assert "A" in result_mixed
    assert "B" in result_mixed
    assert "options=" in result_mixed  # 至少 options= 字符串还在
    # 空字符串不出现
    assert "' '" not in result_mixed  # 纯空白被 trim 后跳过
