"""E2E 测试用 mock LLM。

仅当 ``NEXUS_E2E_MOCK=1`` 时启用(由 :mod:`nexus.backend.agent` 检测),
平时不加载,不影响生产。

设计:NEXUS_E2E_SCENARIO 环境变量决定返回哪种预定义 AIMessage(tool_calls)。
支持 7 类工具场景 + 2 类错误注入场景,覆盖 HITL 全部路径 + 错误兜底:

工具场景:
  - allow_nexus_write:返回 write_file 写到 .nexus/(应直接 allow,无 HITL)
  - interrupt_source:返回 write_file 写 nexus/backend/x.py(应 HITL,用户 approve)
  - interrupt_agents_md:返回 write_file 写 ~/.nexus/AGENTS.md(应 HITL + 评估)
  - deny_tmp_write:返回 write_file 写 /tmp/x.md(应 deny,LLM 看到错误信息)
  - multi_tool_calls:返回 2 个 tool_calls(1 allow + 1 interrupt)— HITL 批处理
  - reject_then_reflect:返回 write_file 写源码 → HITL → reject → 反思不再写
  - edit_file_interrupt:返回 edit_file 改源码(应 HITL)

错误注入场景(每次 invoke 都 raise,不走 _build_message):
  - auth_401:抛 openai.AuthenticationError(密钥失效)→ 走 stream_guard → error 帧
  - rate_limit:抛 openai.RateLimitError(限流)→ 走 stream_guard 重试 + 兜底帧

每次 mock LLM 调用返回一次预定义 AIMessage;后续轮次由 deepagents 自行
处理(approve 后 LLM 不再调工具,reject 后 LLM 反思)。

注:所有路径必须是绝对路径(deepagents FilesystemMiddleware ``validate_path``
拒绝 ``~`` 和相对路径)。``~/.nexus/...`` 场景会自动展开成 ``/Users/yxb/.nexus/...``。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def _home() -> Path:
    """返回 mock 文件应该落到的根目录。

    优先读 :envvar:`NEXUS_HOME`;缺省回到 ``~/.nexus``。

    WHY:Playwright E2E (``playwright.config.ts``)把后端进程的 ``NEXUS_HOME``
    指向 ``/tmp/nexus-playwright-<pid>/``,每个进程独占一份;若 mock 还硬
    编码 ``~/.nexus/outputs/e2e_allow.md``,跨 spec 顺序跑时 :
    - FilesystemBackend 拒绝二次写入(返回 ``Cannot write ... because it
      already exists``)
    - deepagents 模块级单例 ``_agent`` 累积前序 ``ToolMessage``,再次进入
      LLM 时 ``_build_message`` 走 reflection 路径(只有 ``has_tool_result``
      时返回 reflection),emit ``done`` 帧而不是 ``on_chat_model_stream``
      chunk → 前端看不到 stop 按钮 / 流式输出
    """
    return Path(os.environ.get("NEXUS_HOME", str(Path.home() / ".nexus")))


def _abs(path: str) -> str:
    """展开 ``~`` 为绝对路径(deepagents FilesystemMiddleware 拒绝 ``~``)。

    E2E mock 下(NEXUS_E2E_MOCK=1) ``~/.nexus/...`` 自动重定向到
    :envvar:`NEXUS_HOME`,这样后端 deepagents FilesystemMiddleware 仍按
    真实 ``~/.nexus/`` 语义正常放行(allow-list 命中),但文件落到 Playwright
    注入的隔离目录;scenario 写路径保持"写 .nexus/"语义不变,
    FilesystemBackend HITL 不会被触发。
    """
    is_e2e = os.environ.get("NEXUS_E2E_MOCK") == "1"
    home_root = _home()
    if is_e2e and "~/.nexus" in path:
        path = path.replace("~/.nexus", str(home_root))
    return str(Path(path).expanduser().resolve())


def _e2e_path(name: str) -> str:
    """把 scenario 文件名挂到当前 NEXUS_HOME 上,保证 E2E 隔离 + 用户 ``~/.nexus/`` 不被污染。"""
    return str(_home() / "outputs" / name)


_SCENARIOS: dict[str, list[dict[str, Any]]] = {
    # 1. 写 $NEXUS_HOME/.nexus/outputs/e2e_allow.md → 应 allow,无 HITL
    #    E2E 下 _abs() 自动把 ``~/.nexus/...`` 重定向到
    #    :envvar:`NEXUS_HOME` ``/outputs/...``,保证跨 spec 顺序跑时
    #    文件不残留(避免 FilesystemBackend "already exists" → mock
    #    _build_message 误入 reflection 路径) + 用户 ``~/.nexus/`` 不被污染。
    #    deepagents FilesystemMiddleware 看到的仍是 ``.nexus/`` 路径语义,
    #    命中 allow-list 无 HITL,scenario 行为不变。
    "allow_nexus_write": [
        {
            "name": "write_file",
            "args": {
                "file_path": _abs("~/.nexus/outputs/e2e_allow.md"),
                "content": "E2E mock test: .nexus write allowed",
            },
        },
    ],
    # 2. 写项目源码 → 应 HITL,用户 approve 后文件被创建
    "interrupt_source": [
        {
            "name": "write_file",
            "args": {
                "file_path": "/Users/yxb/projects/nexus/nexus/backend/e2e_src.py",
                "content": "print('e2e source interrupt test')",
            },
        },
    ],
    # 3. 写 ~/.nexus/AGENTS.md → HITL + QualityGate 评估
    "interrupt_agents_md": [
        {
            "name": "write_file",
            "args": {
                "file_path": _abs("~/.nexus/AGENTS.md"),
                "content": "# E2E Test Memory\nUser prefers concise responses.",
            },
        },
    ],
    # 4. 写 /tmp → FilesystemMiddleware 应 deny,LLM 看到 "permission denied"
    "deny_tmp_write": [
        {
            "name": "write_file",
            "args": {
                "file_path": "/tmp/e2e_scratch.md",
                "content": "should be denied",
            },
        },
    ],
    # 5. 多个 tool_calls,1 allow + 1 interrupt — deepagents 批处理
    "multi_tool_calls": [
        {
            "name": "write_file",
            "args": {
                "file_path": _abs("~/.nexus/outputs/e2e_multi_a.md"),
                "content": "first call: allow",
            },
        },
        {
            "name": "write_file",
            "args": {
                "file_path": "/Users/yxb/projects/nexus/nexus/backend/e2e_multi_b.py",
                "content": "print('second call: interrupt')",
            },
        },
    ],
    # 6. 写源码 → reject → mock LLM 反思(返回无 tool_call 的纯文本)
    "reject_then_reflect": [
        {
            "name": "write_file",
            "args": {
                "file_path": "/Users/yxb/projects/nexus/nexus/backend/e2e_reject.py",
                "content": "print('about to be rejected')",
            },
        },
    ],
    # 7. edit_file 改源码 → HITL
    # 2026-06-30 重构:``get_project_root`` 在重构后搬到 ``_system_prompt.py``,
    # ``_agent_builder.py`` 里已无此符号。e2e_mock 路径要跟上重构。
    "edit_file_interrupt": [
        {
            "name": "edit_file",
            "args": {
                "file_path": "/Users/yxb/projects/nexus/nexus/backend/agent/_system_prompt.py",
                "old_string": "def get_project_root() -> Path:",
                "new_string": "def get_project_root() -> Path:  # E2E mock comment",
            },
        },
    ],
}


_REFLECTION_TEXTS: dict[str, str] = {
    "reject_then_reflect": "好的,理解了,不再尝试写入项目源码。",
    "default": "操作完成。",
}


class E2EMockChatModel(BaseChatModel):
    """E2E 测试用 mock LLM:每次 invoke 返回下一个 AIMessage(tool_calls)。

    行为契约:
      - ``_SCENARIOS`` 中的场景:第 1 次 invoke 返回预设 tool_calls(模拟
        LLM 决定写文件);后续走反思文本。
      - 特殊场景 ``auth_401``:每次 invoke 都 raise ``AuthenticationError``,
        模拟 LLM 端点 401 错误(密钥失效),走 stream_guard → 前端 error
        帧。验证前端是否兜底回 SetupView 而不是无限 spinner。
      - 特殊场景 ``rate_limit``:每次 invoke 都 raise ``RateLimitError``,
        触发 stream_guard 重试 + 兜底(_exhausted 帧)。

    bind_tools / with_structured_output 返回自身(忽略 schema,因为 mock LLM
    不需要工具 schema — 直接返回预设的 tool_calls)。
    """

    scenario: str = Field(default="allow_nexus_write")
    call_count: int = Field(default=0)

    @property
    def _llm_type(self) -> str:
        return "e2e-mock"

    def _generate(self, messages: list, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        # E2E 流速控制(2026-07-13):stop-mid-stream spec 依赖"流持续一段时间"
        # 才能让用户点 stop。默认 0(mock 立即返回),NEXUS_E2E_MOCK_DELAY_SEC
        # 设成 2 可让流持续 ~2 秒,足以触发 stop 按钮交互。
        delay = float(os.environ.get("NEXUS_E2E_MOCK_DELAY_SEC", "0"))
        # 2026-07-22 调试 hook:看 mock 是不是真 sleep + messages 长度。
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[MOCK-DEBUG] _generate scenario=%s delay=%s messages_len=%s has_tool_result=%s",
            self.scenario,
            delay,
            len(messages) if messages else 0,
            any(isinstance(m, ToolMessage) for m in (messages or [])),
        )
        if delay > 0:
            import time as _time

            _time.sleep(delay)
        # 错误注入场景:每次 invoke 都抛,模拟 LLM 端点错误。
        # WHY:让 stream_guard 走分类 + error 帧路径,验证前端 error 兜底。
        if self.scenario == "auth_401":
            from openai import AuthenticationError

            raise AuthenticationError(
                "Incorrect API key provided",
                response=httpx.Response(401, request=httpx.Request("POST", "/v1/chat/completions")),
                body=None,
            )
        if self.scenario == "rate_limit":
            from openai import RateLimitError

            raise RateLimitError(
                "Rate limit reached",
                response=httpx.Response(429, request=httpx.Request("POST", "/v1/chat/completions")),
                body=None,
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=self._build_message(messages),
                )
            ]
        )

    async def _agenerate(self, messages: list, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)

    def bind_tools(self, tools: Any, **kwargs: Any) -> E2EMockChatModel:
        """忽略工具 schema,返回自身(mock 不需要 schema — 直接返回预设 tool_calls)。

        WHY:create_deep_agent 在初始化时调 ``model.bind_tools(tools)`` 把工具
        schema 传给 LLM。我们 mock LLM 已预定义 tool_calls,不需要再传 schema,
        返回 self 即可让 langchain 链路正常工作。
        """
        return self

    def _build_message(self, messages: list | None = None) -> AIMessage:
        """根据当前消息上下文决定返回 tool_calls 还是反思文本。

        历史实现用 ``call_count`` 计数,问题是 mock instance 进程级单例,
        多 e2e spec 顺序跑会共享 call_count,只有第一个 spec 看到 tool_calls,
        后续全部走反思 → 第二个 spec 期待 HITL 永远不出现。

        改成"context-aware":
          - 历史消息里**有** ToolMessage(无论成功失败)→ 上一轮工具已被
            deepagents 消费,LLM 该反思/收尾
          - 没有 ToolMessage → 首次进入,返回预设 tool_calls

        这样每个新 user prompt 都会触发 tool_calls,HITL/reject/allow
        各种路径都能在多 spec 顺序跑时各自触发。
        """
        has_tool_result = False
        if messages:
            from langchain_core.messages import ToolMessage

            has_tool_result = any(isinstance(m, ToolMessage) for m in messages)

        if has_tool_result:
            # 上一轮工具被消费(可能成功/失败/interrupt resume 后),LLM 收尾
            reflection = _REFLECTION_TEXTS.get(self.scenario, _REFLECTION_TEXTS["default"])
            return AIMessage(content=reflection)

        # 首次进入:返回预设 tool_calls
        tool_calls_spec = _SCENARIOS.get(self.scenario, _SCENARIOS["allow_nexus_write"])
        tool_calls = [
            {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "name": spec["name"],
                "args": spec["args"],
            }
            for spec in tool_calls_spec
        ]
        return AIMessage(content="", tool_calls=tool_calls)


def make_e2e_mock_llm() -> E2EMockChatModel:
    """构造 E2E mock LLM,场景由 ``NEXUS_E2E_SCENARIO`` 决定。"""
    scenario = os.environ.get("NEXUS_E2E_SCENARIO", "allow_nexus_write")
    return E2EMockChatModel(scenario=scenario)
