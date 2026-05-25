from contextlib import asynccontextmanager
import logging
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import CONFIG
from .agent import create_agent

_agent = None

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化，关闭时清理。"""
    global _agent
    _agent = create_agent()
    print("✓ Nexus Backend 已初始化")
    yield
    print("✗ Nexus Backend 关闭中")


app = FastAPI(title="Nexus Backend", lifespan=lifespan)

API_PREFIX = "/api"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(f"{API_PREFIX}/")
async def root():
    return {"message": "Nexus Backend", "version": "1.0.0", "status": "running"}


@app.get(f"{API_PREFIX}/model")
async def get_model_info():
    """获取当前配置的模型信息。"""
    return {
        "model_name": CONFIG["model_name"],
        "temperature": CONFIG["temperature"],
        "api_base": CONFIG["minimax_api_base"],
    }


@app.websocket(f"{API_PREFIX}/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # 维护对话历史
    conversation_history: list[dict] = []

    try:
        while True:
            data = await websocket.receive_json()
            user_content = data.get("content", "")

            if not user_content:
                continue

            # 添加用户消息到历史
            conversation_history.append({"role": "user", "content": user_content})

            full_response = ""
            tool_calls = []

            try:
                for chunk in _agent.stream(
                    {"messages": conversation_history},
                    stream_mode="updates"
                ):
                    if not isinstance(chunk, dict):
                        continue

                    if "model" in chunk:
                        model_data = chunk.get("model")
                        if model_data and isinstance(model_data, dict):
                            messages = model_data.get("messages", [])
                            for msg in messages:
                                msg_content = getattr(msg, "content", "") or ""
                                if msg_content:
                                    full_response += msg_content

                    elif "tool_call" in chunk:
                        tool_name = chunk.get("tool_call", {}).get("name", "未知工具")
                        await websocket.send_json({
                            "type": "thinking",
                            "content": f"[调用工具] {tool_name}",
                        })

                    elif "tool_result" in chunk:
                        result = chunk.get("tool_result", "")
                        await websocket.send_json({
                            "type": "thinking",
                            "content": f"[工具返回] {str(result)[:100]}...",
                        })

                normalized = full_response.replace('<think>', '<thinking>').replace('</think>', '</thinking>')

                chinese_chars = len(re.findall(r'[一-鿿]', normalized))
                english_chars = len(re.findall(r'[a-zA-Z]', normalized))
                other_chars = len(normalized) - chinese_chars - english_chars
                estimated_tokens = int(chinese_chars * 2.5 + english_chars * 0.25 + other_chars * 0.5)
                context_usage = min(int((estimated_tokens / 200000) * 100), 100)

                await websocket.send_json({
                    "type": "token_usage",
                    "content": "",
                    "token_count": estimated_tokens,
                    "context_usage": context_usage
                })

                thinking_parts = re.findall(r'<thinking>(.*?)</thinking>', normalized, flags=re.DOTALL)
                response_text = re.sub(r'<thinking>.*?</thinking>', '', normalized, flags=re.DOTALL).strip()
                thinking_text = '\n'.join(thinking_parts)

                if thinking_parts:
                    all_thinking = '\n'.join(part.strip() for part in thinking_parts)
                    await websocket.send_json({
                        "type": "thinking",
                        "content": all_thinking,
                    })

                if response_text:
                    chunk_size = 3
                    for i in range(0, len(response_text), chunk_size):
                        chunk = response_text[i:i+chunk_size]
                        await websocket.send_json({
                            "type": "chunk",
                            "content": chunk,
                        })

                    await websocket.send_json({
                        "type": "final",
                        "content": response_text,
                    })

                await websocket.send_json({
                    "type": "done",
                    "content": "",
                })

                # 将助手回复添加到历史
                if response_text:
                    conversation_history.append({"role": "assistant", "content": response_text})

            except Exception as e:
                error_msg = str(e)
                logging.error(f"Agent error: {error_msg}")
                await websocket.send_json({
                    "type": "error",
                    "content": error_msg,
                })

    except WebSocketDisconnect:
        print("客户端断开连接")