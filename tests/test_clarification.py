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


# ============== 5. ask_user options 字典形式 → 序列化为 label 字符串 ==============


def test_ask_user_dict_options_normalized_to_labels(monkeypatch) -> None:
    """LLM 传 [{key, label, description}] 字典列表 → 客户端收到 label 字符串列表。

    背景:LLM 调 ask_user 工具时,有时会用更结构化的形式给选项
    (key+label+description),而 ws.py 之前只接 str,导致选项被全过滤
    掉、前端只能看到空 options 自由输入框。修复后规范化成 label 字符串。
    """
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "question": "这次海口 3 日游你更倾向哪种风格?",
                    "options": [
                        {"key": "classic", "label": "经典必玩", "description": "骑楼老街、万绿园等"},
                        {"key": "food", "label": "美食探店", "description": "早茶、海鲜大排档"},
                        {"key": "leisure", "label": "休闲度假", "description": "海边发呆 + 温泉"},
                    ],
                }
            },
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "海口 3 日游", "title": "dict-options-test"})

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
    assert clarify["content"] == "这次海口 3 日游你更倾向哪种风格?"
    # 关键:字典被规范化为 label 字符串,前端按钮才能正常显示
    assert clarify["options"] == ["经典必玩", "美食探店", "休闲度假"]


def test_ask_user_content_field_options(monkeypatch) -> None:
    """MiniMax LLM 用 [{content: "..."}] 字典(MiniMax 默认字段名)。
    之前只认 label/text/value/name,content 被忽略 → options=0,
    前端看到空 options 走自由输入框。
    修复后 content 也加入字段白名单。
    """
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "question": "这次去海口是哪种出行情况?",
                    "options": [
                        {"content": "情侣/夫妻度假"},
                        {"content": "家庭出游(带老人/小孩)"},
                        {"content": "朋友/同学结伴"},
                        {"content": "独自旅行"},
                    ],
                }
            },
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "海口 3 日游", "title": "content-field-test"})

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
    assert clarify["options"] == [
        "情侣/夫妻度假",
        "家庭出游(带老人/小孩)",
        "朋友/同学结伴",
        "独自旅行",
    ]


def test_ask_user_key_only_dict_fallback(monkeypatch) -> None:
    """LLM 用 [{key: "本周末", description: "..."}] 字典(无 label/content/text/value/name)。
    之前 elif 分支错位,label 永远 None → options=0,用户看不到候选。
    修复后 dict 字段白名单 + key 兜底 + str(opt) 兜底,总能抽出可读字符串。
    """
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "question": "出行日期大概在什么时候?",
                    "options": [
                        {"key": "本周末(近期)", "description": "按当前季节气候推荐,3-5 天内出发"},
                        {"key": "下个月", "description": "关注天气预报和台风季"},
                        {"key": "春节/国庆长假", "description": "人流大,行程需要错峰"},
                    ],
                }
            },
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "海口 3 日游", "title": "key-only-test"})

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
    # 关键:key 字段兜底,用户能看到候选按钮
    assert clarify["options"] == [
        "本周末(近期)",
        "下个月",
        "春节/国庆长假",
    ]


def test_ask_user_mixed_options(monkeypatch) -> None:
    """options 同时含字符串、字典、空串、None → 只保留有效项。"""
    _authed_token(monkeypatch)

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        yield {
            "event": "on_tool_start",
            "name": "ask_user",
            "data": {
                "input": {
                    "question": "选哪个?",
                    "options": [
                        "纯字符串",
                        {"label": "字典label"},
                        {"text": "字典text"},
                        "",  # 空字符串
                        {"label": ""},  # 字典但 label 空
                        None,  # None
                    ],
                }
            },
        }

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                ws.send_json({"content": "选", "title": "mixed-options-test"})

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
    # 关键:有效项保留,空串/None 跳过
    assert clarify["options"] == ["纯字符串", "字典label", "字典text"]


# ============== 6. clarification 占位入库失败不影响 ws 协议 ==============


def test_clarification_placeholder_persist_failure_does_not_kill_ws(monkeypatch) -> None:
    """add_message 在 clarification 占位写入失败(模拟 aiosqlite 持 WAL 锁)
    → ws 不应崩,后续消息能继续处理。

    背景:deepagents 的 AsyncSqliteStore/AsyncSqliteSaver 持有 WAL 写锁时
    busy_timeout=30s 仍然不够,OperationalError("database is locked") 抛
    到 handle_websocket 外层,导致 ws 连接进入死循环("WS 收到非 JSON 帧"
    每 15s 重现)。修复后:_finalize_after_stream 的 clarification 分支
    包 try/except,失败降级为 warning log。
    """
    from unittest.mock import patch as _patch

    _authed_token(monkeypatch)

    call_count = {"n": 0}

    async def astream_events_factory(input, **kwargs):  # noqa: ARG001
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 第一次 turn:LLM 决定追问
            yield {
                "event": "on_tool_start",
                "name": "ask_user",
                "data": {
                    "input": {
                        "question": "需要什么?",
                        "options": ["A", "B"],
                    }
                },
            }
        else:
            # 第二次 turn:LLM 给正常回复
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": MagicMock(content="done reply")},
            }

    from nexus.backend import db as _db_module

    real_add_message = _db_module.add_message

    def fake_add_message(*args, **kwargs):
        # add_message(message_id, session_id, role, content, ...)
        role = args[2] if len(args) > 2 else kwargs.get("role")
        content = args[3] if len(args) > 3 else kwargs.get("content", "")
        if role == "assistant" and str(content).startswith("[澄清中]"):
            raise Exception("database is locked")
        return real_add_message(*args, **kwargs)

    with TestClient(app) as client:
        with patch("nexus.backend.main._agent") as mock_agent:
            mock_agent.astream_events = astream_events_factory

            with client.websocket_connect("/api/ws?token=test-token") as ws:
                # 第一次 turn → 触发 clarification；只模拟 clarification 占位入库失败。
                with _patch("nexus.backend.db.add_message", side_effect=fake_add_message):
                    ws.send_json({"content": "Q1", "title": "lock-test"})
                    first_events: list[dict] = []
                    for _ in range(20):
                        try:
                            msg = ws.receive_json()
                        except Exception:
                            break
                        first_events.append(msg)
                        if msg.get("type") == "clarification_request":
                            break

                # 关键断言 1:仍然收到 clarification_request(add_message 失败不阻断协议)
                assert any(e.get("type") == "clarification_request" for e in first_events), (
                    f"未收到 clarification_request: {first_events}"
                )

                # 第二次 turn → LLM 正常回复(ws 没被第一次锁异常打死)
                ws.send_json({"content": "Q2", "title": "lock-test-2"})
                second_events: list[dict] = []
                for _ in range(20):
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    second_events.append(msg)
                    if msg.get("type") == "done":
                        break

                # 关键断言 2:第二次 turn 仍能收到 done(ws 没被锁异常打死)
                assert any(e.get("type") == "done" for e in second_events), f"第二次 turn 未完成: {second_events}"
