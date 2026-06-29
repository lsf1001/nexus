"""E2E 测试用 mock LLM。

仅当 ``NEXUS_E2E_MOCK=1`` 时启用(由 :mod:`nexus.backend.agent` 检测),
平时不加载,不影响生产。

设计:NEXUS_E2E_SCENARIO 环境变量决定返回哪种预定义 AIMessage(tool_calls)。
支持 7 类场景,覆盖 HITL 全部路径:

  - allow_nexus_write:返回 write_file 写到 .nexus/(应直接 allow,无 HITL)
  - interrupt_source:返回 write_file 写 nexus/backend/x.py(应 HITL,用户 approve)
  - interrupt_agents_md:返回 write_file 写 ~/.nexus/AGENTS.md(应 HITL + 评估)
  - deny_tmp_write:返回 write_file 写 /tmp/x.md(应 deny,LLM 看到错误信息)
  - multi_tool_calls:返回 2 个 tool_calls(1 allow + 1 interrupt)— HITL 批处理
  - reject_then_reflect:返回 write_file 写源码 → HITL → reject → 反思不再写
  - edit_file_interrupt:返回 edit_file 改源码(应 HITL)

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

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def _abs(path: str) -> str:
    """展开 ``~`` 为绝对路径(deepagents FilesystemMiddleware 拒绝 ``~``)。"""
    return str(Path(path).expanduser().resolve())


_SCENARIOS: dict[str, list[dict[str, Any]]] = {
    # 1. 写 .nexus/ → 应 allow,无 HITL
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
      - 第 1 次 invoke:返回 ``_SCENARIOS[scenario][0]`` 的 tool_calls(预定义)
      - 第 2 次 invoke(模拟 approve 后):返回无 tool_call 的 AIMessage(LLM 反思)
      - 第 3+ 次 invoke:同样返回反思文本(防止 deepagents 循环)

    bind_tools / with_structured_output 返回自身(忽略 schema,因为 mock LLM
    不需要工具 schema — 直接返回预设的 tool_calls)。
    """

    scenario: str = Field(default="allow_nexus_write")
    call_count: int = Field(default=0)

    @property
    def _llm_type(self) -> str:
        return "e2e-mock"

    def _generate(self, messages: list, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
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
