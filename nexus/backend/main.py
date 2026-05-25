from contextlib import asynccontextmanager
import logging
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import CONFIG
from .agent import create_agent
from .models_config import load_models, get_active_model, set_active_model

_agent = None

logging.basicConfig(level=logging.INFO)


def _create_agent_with_model(model_config: dict | None = None):
    """使用指定模型配置创建 Agent。"""
    if model_config is None:
        model_config = get_active_model()
    return create_agent(
        model_name=model_config.get("name", "MiniMax-M2.7") if model_config else "MiniMax-M2.7",
        api_key=model_config.get("api_key", CONFIG["minimax_api_key"]) if model_config else CONFIG["minimax_api_key"],
        api_base=model_config.get("api_base", CONFIG["minimax_api_base"]) if model_config else CONFIG["minimax_api_base"],
        temperature=model_config.get("temperature", 0.7) if model_config else 0.7,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化，关闭时清理。"""
    global _agent
    _agent = _create_agent_with_model()
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
    """获取当前激活的模型信息。"""
    active = get_active_model()
    if active:
        return {
            "model_name": active.get("name", "MiniMax-M2.7"),
            "temperature": active.get("temperature", 0.7),
            "api_base": active.get("api_base", CONFIG["minimax_api_base"]),
            "id": active.get("id"),
        }
    return {
        "model_name": CONFIG["model_name"],
        "temperature": CONFIG["temperature"],
        "api_base": CONFIG["minimax_api_base"],
    }


@app.get(f"{API_PREFIX}/models")
async def get_models():
    """获取所有模型列表。"""
    config = load_models()
    return config.get("models", [])


@app.post(f"{API_PREFIX}/models/switch")
async def switch_model(body: dict):
    """切换当前激活的模型。"""
    global _agent
    model_id = body.get("id")
    if not model_id:
        return {"error": "缺少模型ID"}

    active = set_active_model(model_id)
    if not active:
        return {"error": "模型不存在"}

    # 重新创建 Agent
    _agent = _create_agent_with_model(active)
    return {
        "success": True,
        "active_model": {
            "id": active.get("id"),
            "name": active.get("name"),
        }
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