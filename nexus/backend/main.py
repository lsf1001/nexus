from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import CONFIG
from .database import init_db
from .agent import create_agent
from .session import create_session, get_conversation_history, add_message, get_session_settings

# 全局智能体实例
_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化，关闭时清理。"""
    global _agent
    await init_db()
    _agent = create_agent()
    print("✓ Nexus Backend 已初始化")
    yield
    print("✗ Nexus Backend 关闭中")


app = FastAPI(title="Nexus Backend", lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Nexus Backend", "version": "1.0.0"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str = None):
    await websocket.accept()

    # 如果未提供 session_id，创建新会话
    if not session_id:
        session_id = await create_session()
        await websocket.send_json({"type": "session_created", "session_id": session_id})

    settings = await get_session_settings(session_id)
    show_thinking = settings.get("show_thinking", True)

    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()
            user_content = data.get("content", "")

            if not user_content:
                continue

            # 保存用户消息
            await add_message(session_id, "user", user_content)

            # 获取对话历史
            history = await get_conversation_history(session_id)

            # 添加当前消息
            history.append({"role": "user", "content": user_content})

            # 通过智能体流式处理
            thinking_buffer = ""

            try:
                for chunk in _agent.stream(
                    {"messages": history},
                    stream_mode="updates"
                ):
                    if not isinstance(chunk, dict):
                        continue

                    # 从 chunk 中提取 AI 消息内容
                    model_data = chunk.get("model")
                    if model_data and isinstance(model_data, dict):
                        messages = model_data.get("messages", [])
                        for msg in messages:
                            if hasattr(msg, "content") and msg.content:
                                content = msg.content
                                if content.strip():
                                    if show_thinking:
                                        await websocket.send_json({
                                            "type": "thinking",
                                            "content": content,
                                            "session_id": session_id
                                        })
                                    thinking_buffer += content

                # 发送最终响应
                final_content = thinking_buffer.strip() if thinking_buffer else ""
                if final_content:
                    await websocket.send_json({
                        "type": "final",
                        "content": final_content,
                        "session_id": session_id
                    })
                    await add_message(session_id, "assistant", final_content, thinking_buffer)

                await websocket.send_json({
                    "type": "done",
                    "content": "",
                    "session_id": session_id
                })

            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "content": str(e),
                    "session_id": session_id
                })

    except WebSocketDisconnect:
        print(f"客户端断开连接: {session_id}")