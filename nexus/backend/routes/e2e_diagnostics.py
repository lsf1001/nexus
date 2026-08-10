"""E2E 测试专用诊断端点 — 仅 NEXUS_E2E_MOCK=1 时挂载。

WHY:Playwright spec 需要断言 LLM 真的收到图(图片注入链路是 Round 2 T3
的实现,本轮端到端验证)。生产路径不应该暴露最后消息内容。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException

from ..llm.e2e_mock import E2EMockChatModel

router = APIRouter(prefix="/api/e2e", tags=["e2e-diagnostics"])

_e2e_mock_instance: E2EMockChatModel | None = None


def register_e2e_mock(instance: E2EMockChatModel) -> None:
    """E2EMockChatModel 实例由 agent builder 创建后,通过本函数注册。

    WHY 单例 + 注册:agent builder 创建的 mock 实例按 lazy init 路径走,
    没有全局可访问的"全局变量"。路由层独立声明,但路由又需要读这个实例
    的 last_messages 字段暴露给 E2E — 因此通过 register 函数单向注入,
    不让路由直接 import agent builder(避免循环 + 让 E2E 路由不依赖
    真实 LLM 路径)。
    """
    global _e2e_mock_instance
    _e2e_mock_instance = instance


@router.get("/last-messages")
async def get_last_messages() -> dict[str, Any]:
    """读取 mock LLM 最后一次 _generate 收到的 messages 列表。

    仅当 :envvar:`NEXUS_E2E_MOCK` == ``"1"`` 时返回数据,否则 404 —
    生产路径不应暴露 last_messages 给任何人。

    序列化规则:
      - HumanMessage.content 可能是 list(content blocks,Anthropic multi-part);
        把每个 block 拍平成 ``{"type": ..., ...}``
      - 字符串 content 原样返回
    """
    if os.environ.get("NEXUS_E2E_MOCK") != "1":
        raise HTTPException(404, "not in E2E mode")
    if _e2e_mock_instance is None:
        return {"messages": []}
    serialized = []
    for m in _e2e_mock_instance.last_messages:
        content = m.content
        if isinstance(content, list):
            content = [
                {
                    "type": b.get("type", "unknown") if isinstance(b, dict) else "unknown",
                    **({"value": str(b)} if not isinstance(b, dict) else b),
                }
                for b in content
            ]
        serialized.append({"type": type(m).__name__, "content": content})
    return {"messages": serialized}
