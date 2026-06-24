"""数据模型定义。

使用 Pydantic 提供类型安全和验证。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WSMessage(BaseModel):
    """WebSocket 传入消息。"""

    session_id: str | None = None
    content: str = Field(..., min_length=1, description="消息内容")


class StreamEvent(BaseModel):
    """WebSocket 传出事件。"""

    type: str = Field(..., pattern="^(thinking|tool_call|tool_result|final|done)$", description="事件类型")
    content: str
    session_id: str


class Session(BaseModel):
    """会话模型。"""

    id: str = Field(..., min_length=1)
    title: str | None = Field(default=None, max_length=100)
    show_thinking: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Message(BaseModel):
    """消息模型。"""

    id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    thinking_content: str | None = None
    created_at: datetime | None = None


class ModelConfig(BaseModel):
    """模型配置。"""

    id: str = Field(..., min_length=1, description="模型ID")
    name: str = Field(default="MiniMax-M3", description="模型名称")
    api_key: str | None = Field(default=None, description="API密钥")
    api_base: str | None = Field(default=None, description="API端点")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    is_active: bool = False


class SwitchModelRequest(BaseModel):
    """切换模型请求。"""

    id: str = Field(..., min_length=1, description="目标模型ID")


class SwitchModelResponse(BaseModel):
    """切换模型响应。"""

    success: bool
    error: str | None = None
    active_model: dict | None = None


class TokenUsage(BaseModel):
    """Token 使用情况。"""

    type: str = "token_usage"
    token_count: int = Field(ge=0)
    context_usage: int = Field(ge=0, le=100, description="上下文使用百分比")


# === HITL(Human-in-the-Loop)桥接 WS 帧 schema ===
#
# WHY:langchain HumanInTheLoopMiddleware 在 ``astream_events`` 中抛
# ``GraphInterrupt(interrupts=[Interrupt(value=hitl_request, id=...)])``。
# WS 层 ``_run_agent_streaming`` 把 hitl_request 翻成 ``confirmation_request``
# 帧推给前端;前端把决策装成 ``confirmation_response`` 帧推回,WS 层
# ``handle_websocket`` 装成 ``Command(resume={"decisions": [...]})`` 续流。
# 这些 schema 只描述 WS 帧形状,不入库。


class ConfirmationActionOption(BaseModel):
    """HITL 决策选项(给前端的可选项)。"""

    label: str = Field(..., description="按钮文案,如 '批准' / '拒绝'")
    decision: Literal["approve", "reject"] = Field(..., description="决策码")


class ConfirmationAction(BaseModel):
    """HITL 待审批动作(对应 langchain HITLRequest.action_requests 一项)。"""

    tool_name: str = Field(..., description="工具名,如 'write_file'")
    target_path: str = Field(..., description="目标路径")
    preview: str = Field(default="", description="新内容预览(已截断)")
    description: str = Field(default="", description="HITL 描述")
    options: list[ConfirmationActionOption] = Field(
        default_factory=list,
        description="可选决策,固定为 approve / reject 两项",
    )


class ConfirmationRequest(BaseModel):
    """HITL 确认请求帧(server → client)。"""

    type: Literal["confirmation_request"] = "confirmation_request"
    event_id: int = Field(..., description="递增事件 ID")
    interrupt_id: str = Field(..., description="langgraph Interrupt.id,续流用")
    actions: list[ConfirmationAction] = Field(default_factory=list)


class ConfirmationResponse(BaseModel):
    """HITL 确认响应帧(client → server)。"""

    type: Literal["confirmation_response"] = "confirmation_response"
    event_id: int = Field(..., description="对应 confirmation_request 的 event_id")
    interrupt_id: str = Field(..., description="对应 confirmation_request 的 interrupt_id")
    decision: Literal["approve", "reject"] = Field(..., description="决策")
