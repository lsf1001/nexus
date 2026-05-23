# Nexus 后端实现计划

> **执行方式:** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 技能逐任务执行。

**目标:** 构建支持 WebSocket 的 FastAPI 后端，集成 DeepAgents，管理 SQLite 会话，为 Nexus AI Agent 提供服务。

**架构:** FastAPI 处理 WebSocket 连接，在 SQLite 中管理会话状态，并将 DeepAgents 输出流式推送给客户端。

**技术栈:** FastAPI, uvicorn, deepagents==0.5.3, langchain-openai, duckduckgo-search, aiosqlite

---

## 文件结构

```
nexus/backend/
├── main.py           # FastAPI 应用、WebSocket 端点、生命周期
├── config.py         # 环境配置加载
├── database.py      # SQLite 连接和表
├── models.py         # 请求/响应 Pydantic 模型
├── agent.py         # DeepAgents 封装
├── tools.py         # 自定义工具
├── session.py        # 会话管理
└── requirements.txt # Python 依赖
```

---

## 任务 1: 项目初始化

**文件:**
- 创建: `nexus/backend/requirements.txt`
- 创建: `nexus/backend/config.py`

- [ ] **步骤 1: 创建 requirements.txt**

```
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
deepagents==0.5.3
langchain-openai>=1.0.0
langchain-community>=0.0.20
duckduckgo-search>=4.0.0
aiosqlite>=0.19.0
pydantic>=2.0.0
python-dotenv>=1.0.0
```

- [ ] **步骤 2: 创建 config.py**

```python
import os
import json
from pathlib import Path

def load_config() -> dict:
    """从环境变量和配置文件加载配置。"""
    config = {
        "minimax_api_key": os.environ.get("MiniMax_API_KEY", ""),
        "minimax_api_base": os.environ.get("MiniMax_API_BASE", "https://api.minimaxi.com/v1"),
        "database_url": os.environ.get("DATABASE_URL", "./nexus.db"),
        "server_host": os.environ.get("SERVER_HOST", "0.0.0.0"),
        "server_port": int(os.environ.get("SERVER_PORT", "8000")),
    }

    # 如果环境变量未设置，从 ~/.claude/settings.json 读取
    if not config["minimax_api_key"]:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path) as f:
                    settings = json.load(f)
                config["minimax_api_key"] = settings.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
            except Exception:
                pass

    return config

CONFIG = load_config()
```

- [ ] **步骤 3: 提交**

```bash
git add nexus/backend/requirements.txt nexus/backend/config.py
git commit -m "feat: 添加项目初始化和配置"
```

---

## 任务 2: 数据库初始化

**文件:**
- 创建: `nexus/backend/database.py`
- 创建: `nexus/backend/models.py`

- [ ] **步骤 1: 创建 database.py**

```python
import aiosqlite

DATABASE_PATH = "./nexus.db"

INIT_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    show_thinking BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    thinking_content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
"""

async def init_db():
    """初始化数据库表。"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript(INIT_SQL)
        await db.commit()

async def get_db():
    """获取数据库连接。"""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
```

- [ ] **步骤 2: 创建 models.py**

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WSMessage(BaseModel):
    """WebSocket 传入消息。"""
    session_id: Optional[str] = None
    content: str

class StreamEvent(BaseModel):
    """WebSocket 传出事件。"""
    type: str  # thinking, tool_call, tool_result, final, done
    content: str
    session_id: str

class Session(BaseModel):
    """会话模型。"""
    id: str
    title: Optional[str] = None
    show_thinking: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Message(BaseModel):
    """消息模型。"""
    id: str
    session_id: str
    role: str  # user / assistant
    content: str
    thinking_content: Optional[str] = None
    created_at: Optional[datetime] = None
```

- [ ] **步骤 3: 提交**

```bash
git add nexus/backend/database.py nexus/backend/models.py
git commit -m "feat: 添加数据库和模型"
```

---

## 任务 3: 自定义工具

**文件:**
- 创建: `nexus/backend/tools.py`

- [ ] **步骤 1: 创建 tools.py**

```python
import datetime
from langchain_core.tools import tool as langchain_tool
from langchain_community.tools import DuckDuckGoSearchRun

@langchain_tool
def get_current_date() -> str:
    """获取今天的日期，格式 YYYY-MM-DD。"""
    today = datetime.date.today()
    return today.strftime("%Y-%m-%d")

web_search = DuckDuckGoSearchRun(name="web_search", description="搜索网络信息")

TOOLS = [get_current_date, web_search]
```

- [ ] **步骤 2: 提交**

```bash
git add nexus/backend/tools.py
git commit -m "feat: 添加自定义工具"
```

---

## 任务 4: DeepAgents 封装

**文件:**
- 创建: `nexus/backend/agent.py`

- [ ] **步骤 1: 创建 agent.py**

```python
from typing import Any
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from config import CONFIG

def get_llm() -> ChatOpenAI:
    """创建 MiniMax 配置的 ChatOpenAI 实例。"""
    return ChatOpenAI(
        model="MiniMax-M2.7",
        openai_api_key=CONFIG["minimax_api_key"],
        openai_api_base=CONFIG["minimax_api_base"],
        temperature=0.7,
    )

def create_agent() -> Any:
    """创建带工具的 DeepAgents 智能体。"""
    from tools import TOOLS

    return create_deep_agent(
        model=get_llm(),
        tools=TOOLS,
    )

def is_research_topic(topic: str) -> bool:
    """判断主题是否需要研究模式。"""
    research_keywords = ["研究", "分析", "调查", "报告", "对比", "趋势", "原理", "机制", "技术", "方案"]
    simple_keywords = ["今天", "明天", "昨天", "几号", "星期几", "你好", "谢谢", "再见", "1+1", "天气"]

    topic_lower = topic.lower()

    for keyword in research_keywords:
        if keyword in topic_lower:
            return True

    for keyword in simple_keywords:
        if keyword in topic_lower:
            return len(topic) > 20

    return len(topic) > 20
```

- [ ] **步骤 2: 提交**

```bash
git add nexus/backend/agent.py
git commit -m "feat: 添加 DeepAgents 封装"
```

---

## 任务 5: 会话管理

**文件:**
- 创建: `nexus/backend/session.py`

- [ ] **步骤 1: 创建 session.py**

```python
import uuid
from datetime import datetime
from typing import Optional
import aiosqlite
from database import DATABASE_PATH

async def create_session(title: str = None, show_thinking: bool = True) -> str:
    """创建新会话，返回 session_id。"""
    session_id = str(uuid.uuid4())
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO sessions (id, title, show_thinking) VALUES (?, ?, ?)",
            (session_id, title or "新对话", show_thinking)
        )
        await db.commit()
    return session_id

async def get_session(session_id: str) -> Optional[dict]:
    """根据 ID 获取会话。"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def add_message(session_id: str, role: str, content: str, thinking_content: str = None) -> str:
    """添加消息到会话，返回 message_id。"""
    message_id = str(uuid.uuid4())
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO messages (id, session_id, role, content, thinking_content) VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, thinking_content)
        )
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), session_id)
        )
        await db.commit()
    return message_id

async def get_conversation_history(session_id: str) -> list[dict]:
    """获取对话历史，格式化为 DeepAgents 所需格式。"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]

async def get_session_settings(session_id: str) -> dict:
    """获取会话设置。"""
    session = await get_session(session_id)
    return {"show_thinking": session.get("show_thinking", True)} if session else {"show_thinking": True}
```

- [ ] **步骤 2: 提交**

```bash
git add nexus/backend/session.py
git commit -m "feat: 添加会话管理"
```

---

## 任务 6: WebSocket 端点

**文件:**
- 创建: `nexus/backend/main.py`

- [ ] **步骤 1: 创建 main.py (Part 1: 设置)**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from config import CONFIG
from database import init_db
from agent import create_agent, is_research_topic
from session import create_session, get_conversation_history, add_message, get_session_settings

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
                    stream_mode="messages"
                ):
                    if not isinstance(chunk, tuple) or len(chunk) < 1:
                        continue

                    msg = chunk[0]
                    msg_type = getattr(msg, "type", "unknown")
                    content = getattr(msg, "content", "") or ""

                    if msg_type == "ai":
                        if content.strip():
                            if show_thinking:
                                await websocket.send_json({
                                    "type": "thinking",
                                    "content": content,
                                    "session_id": session_id
                                })
                            thinking_buffer += content

                    elif msg_type == "tool":
                        await websocket.send_json({
                            "type": "tool_result",
                            "content": content,
                            "session_id": session_id
                        })

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
```

- [ ] **步骤 2: 验证导入**

运行: `cd nexus/backend && python -c "from main import app; print('导入成功')"`
预期: 无错误

- [ ] **步骤 3: 提交**

```bash
git add nexus/backend/main.py
git commit -m "feat: 添加 WebSocket 端点"
```

---

## 任务 7: 运行脚本

**文件:**
- 创建: `nexus/backend/run.py`

- [ ] **步骤 1: 创建 run.py**

```python
import uvicorn
from config import CONFIG

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=CONFIG["server_host"],
        port=CONFIG["server_port"],
        reload=True,
    )
```

- [ ] **步骤 2: 测试启动**

运行: `cd nexus/backend && python run.py &`
预期: 服务在 8000 端口启动

运行: `curl http://localhost:8000/`
预期: `{"message":"Nexus Backend","version":"1.0.0"}`

- [ ] **步骤 3: 提交**

```bash
git add nexus/backend/run.py
git commit -m "feat: 添加运行脚本"
git log --oneline -5
```

---

## 自检清单

1. **需求覆盖:** 检查 PRD.md 每个部分是否有对应任务
   - [x] FastAPI 项目 - 任务 1, 6
   - [x] WebSocket 端点 - 任务 6
   - [x] DeepAgents 集成 - 任务 4, 6
   - [x] SQLite 会话管理 - 任务 2, 5
   - [x] 自定义工具 - 任务 3
   - [x] 环境配置 - 任务 1

2. **占位符扫描:** 无 "TBD"、"TODO"、"后续实现" 等

3. **类型一致性:** 函数签名在各文件中匹配

---

**计划已保存至:** `nexus/docs/superpowers/plans/2026-05-23-nexus-backend.md`

**执行选项:**

1. **Subagent-Driven (推荐)** - 我为每个任务启动独立子 agent，任务间 review，快速迭代

2. **Inline Execution** - 在当前 session 使用 executing-plans 执行，带检查点的批量执行

选哪个？