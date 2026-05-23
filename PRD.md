# Nexus PRD - 智能研究助手

## 1. 产品概述

| 属性   | 值                                 |
| ---- | --------------------------------- |
| 产品名称 | Nexus                             |
| 开发公司 | 夜小白科技有限公司                         |
| 产品类型 | AI Agent Web 应用                   |
| 核心功能 | 用户输入研究主题，Agent 自动搜索、规划、执行，生成结构化报告 |
| 技术原则 | 基于 DeepAgents SDK，不过度封装，不造轮子      |

## 2. 技术架构

### 2.1 技术栈

| 组件       | 技术               | 说明             |
| -------- | ---------------- | -------------- |
| 前端       | React            | SPA 应用         |
| 后端       | FastAPI          | Python ASGI 框架 |
| Agent 框架 | DeepAgents 0.5.3 | SDK，不过度封装      |
| LLM      | MiniMax-M2.7     | OpenAI SDK 兼容  |
| 通信协议     | WebSocket        | 实时流式双向通信       |
| 会话存储     | SQLite           | 自建表结构          |

### 2.2 项目结构

```
nexus/
├── backend/
│   ├── main.py              # FastAPI 入口 + WebSocket + DeepAgents
│   ├── config.py            # 配置管理
│   ├── database.py          # SQLite 连接和表
│   ├── models.py            # Pydantic 模型
│   ├── agent.py             # DeepAgents 封装
│   ├── tools.py             # 自定义工具
│   ├── session.py           # 会话管理
│   ├── run.py               # 运行脚本
│   └── requirements.txt
│
└── frontend/
    └── (React 项目)
```

### 2.3 技术栈

| 组件       | 技术               | 说明             |
| -------- | ---------------- | -------------- |
| 前端框架     | React + Vite     | SPA 应用         |
| 样式       | Tailwind CSS     | 自定义组件          |
| 状态管理     | Zustand          | 轻量状态管理         |
| 后端       | FastAPI          | Python ASGI 框架 |
| Agent 框架 | DeepAgents 0.5.3 | SDK，不过度封装      |
| LLM      | MiniMax-M2.7 等   | OpenAI SDK 兼容  |
| 通信协议     | WebSocket        | 实时流式双向通信       |
| 会话存储     | SQLite           | 自建表结构          |
| Token 计算 | tiktoken         | 上下文用量计算        |

### 2.3 系统架构图

```
┌─────────────┐         WebSocket          ┌─────────────┐
│   React     │ ◄─────────────────────────► │   FastAPI   │
│   Frontend  │                             │   Backend   │
└─────────────┘                             └──────┬──────┘
                                                   │
                                            ┌──────▼──────┐
                                            │ DeepAgents  │
                                            │    SDK      │
                                            └──────┬──────┘
                                                   │
                                            ┌──────▼──────┐
                                            │  MiniMax    │
                                            │   LLM       │
                                            └─────────────┘
```

## 3. API 设计

### 3.1 WebSocket 连接

- **端点**: `ws://localhost:8000/ws`
- **连接参数**: `?session_id=xxx` (可选，新建会话时为空)

### 3.2 客户端发送消息

```json
{
  "session_id": "uuid-xxx",
  "content": "今天几号"
}
```

| 字段         | 类型     | 必填  | 说明           |
| ---------- | ------ | --- | ------------ |
| session_id | string | 否   | 会话ID，空表示新建会话 |
| content    | string | 是   | 消息内容         |

### 3.3 服务端推送消息

```json
{
  "type": "thinking",
  "content": "用户问今天几号，我需要调用工具...",
  "session_id": "uuid-xxx"
}

{
  "type": "tool_call",
  "content": "get_current_date",
  "session_id": "uuid-xxx"
}

{
  "type": "tool_result",
  "content": "2026-05-23",
  "session_id": "uuid-xxx"
}

{
  "type": "final",
  "content": "今天是2026年5月23日",
  "session_id": "uuid-xxx"
}

{
  "type": "done",
  "content": "",
  "session_id": "uuid-xxx"
}
```

| type        | 说明         |
| ----------- | ---------- |
| thinking    | Agent 思考过程 |
| tool_call   | 工具调用开始     |
| tool_result | 工具返回结果     |
| final       | 最终回复       |
| done        | 结束信号       |

## 4. 数据库设计

### 4.1 表结构

```sql
-- 会话表
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    show_thinking BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 消息表
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- user / assistant
    content TEXT NOT NULL,
    thinking_content TEXT,       -- 思考过程（可选存储）
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

### 4.2 索引

```sql
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_sessions_updated ON sessions(updated_at);
```

## 5. DeepAgents 集成

### 5.1 模型配置

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="MiniMax-M2.7",
    openai_api_key=os.environ.get("MiniMax_API_KEY"),
    openai_api_base="https://api.minimaxi.com/v1",
    temperature=0.7,
)
```

### 5.2 Agent 创建

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=llm,
    tools=[get_current_date, web_search],
)
```

### 5.3 模型配置

```python
MODELS = {
    "MiniMax-M2.7": {
        "context_window": 200000,
        "api_base": "https://api.minimaxi.com/v1",
    },
    "MiniMax-M2.8": {
        "context_window": 200000,
        "api_base": "https://api.minimaxi.com/v1",
    },
    "DeepSeek-V3": {
        "context_window": 128000,
        "api_base": "https://api.deepseek.com/v1",
    },
}
```

### 5.4 模型配置

```python
MODELS = {
    "MiniMax-M2.7": {
        "context_window": 200000,
        "api_base": "https://api.minimaxi.com/v1",
        "api_key": os.environ.get("MiniMax_API_KEY"),
    },
}
```

**注意：** 当前仅支持 MiniMax-M2.7，后续可根据需要添加更多模型。

### 5.5 内置工具

| 工具                                               | 说明                      |
| ------------------------------------------------ | ----------------------- |
| write_todos                                      | 任务规划                    |
| ls, read_file, write_file, edit_file, glob, grep | 文件操作                    |
| execute                                          | Shell 命令（需要 backend 支持） |
| task                                             | 子智能体委派                  |

### 5.6 自定义工具

| 工具               | 说明                   |
| ---------------- | -------------------- |
| get_current_date | 获取当天日期，格式 YYYY-MM-DD |
| web_search       | DuckDuckGo 搜索        |

## 6. 任务模式

### 6.1 自动判断逻辑

```python
def is_research_topic(topic: str) -> bool:
    """
    研究类关键词：研究、分析、调查、报告、对比、趋势、原理、技术、方案
    简单问答关键词：今天、明天、昨天、几号、星期几、你、你好、谢谢、再见、1+1、计算、天气

    - 包含研究关键词 → research
    - 只有简单问答关键词 → simple_chat
    - 内容较长(>20字符)但无研究关键词 → research
    """
```

### 6.2 模式差异

| 模式          | 触发条件 | 行为                   |
| ----------- | ---- | -------------------- |
| simple_chat | 简单问答 | 快速回复，跳过详细规划          |
| research    | 研究任务 | 完整流程：规划→搜索→并行研究→汇总报告 |

## 7. 前端界面设计

### 7.1 技术栈

| 项目   | 技术                   |
| ---- | -------------------- |
| 框架   | React + Vite         |
| 样式   | Tailwind CSS + 自定义组件 |
| 状态管理 | Zustand              |
| 组件   | 自定义（无 UI 组件库）        |

### 7.2 布局结构

```
┌──────────────────────────────────────────────────┐
│  📋 会话                                  ⚙️     │
├──────────────┬─────────────────────────────────┤
│              │                                 │
│  会话1       │   消息区域                       │
│  会话2       │   (scrollable)                   │
│  会话3       │                                 │
│  ...         │                                 │
│              │                                 │
├──────────────┼─────────────────────────────────┤
│ + 新建会话   │ [☐ 思考] [输入框...    ] [发送] │
└──────────────┴─────────────────────────────────┘
```

### 7.3 设置面板

```
┌──────────────────────────────────────────────────┐
│  ⚙️ 设置                           [×]           │
├──────────────────────────────────────────────────┤
│                                                  │
│  模型                  上下文用量                  │
│  ┌────────────────┐  ████████████░░░░░░░░       │
│  │ MiniMax-M2.7 ▼ │  71% (142K/200K)              │
│  └────────────────┘                              │
│                                                  │
│  可用模型:                                       │
│  • MiniMax-M2.7 (200K context)                   │
│                                                  │
│  ☑ 显示思考过程                                  │
│                                                  │
│            [保存]                               │
└──────────────────────────────────────────────────┘
```

### 7.4 消息气泡

| 类型    | 内容                           |
| ----- | ---------------------------- |
| 用户消息  | 右对齐，蓝色背景                     |
| AI 思考 | 可折叠，显示推理过程                   |
| 工具调用  | 可折叠，显示 tool_call/tool_result |
| AI 回复 | 左对齐，灰色背景，最终回复                |

### 7.5 状态管理

```typescript
interface AppState {
  // 会话
  sessions: Session[];
  currentSessionId: string;

  // 消息
  messages: Record<string, Message[]>;

  // 设置
  currentModel: string;
  models: ModelConfig[];
  showThinking: boolean;

  // 连接
  wsConnected: boolean;
  contextUsage: number;  // 当前 token 用量
}
```

### 7.6 Token 计算

使用 tiktoken 计算消息 token 数：

- 编码: `cl100k_base`
- 公式: 用量 = 已用 token / context_window * 100%

## 8. 配置管理

### 8.1 环境变量

| 变量               | 说明        | 默认值                          |
| ---------------- | --------- | ---------------------------- |
| MiniMax_API_KEY  | API Key   | 从 ~/.claude/settings.json 读取 |
| MiniMax_API_BASE | API 端点    | https://api.minimaxi.com/v1  |
| DATABASE_URL     | SQLite 路径 | ./nexus.db                   |
| SERVER_HOST      | 服务地址      | 0.0.0.0                      |
| SERVER_PORT      | 服务端口      | 8000                         |

## 9. 依赖清单

### 9.1 Python 依赖

```
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
deepagents==0.5.3
langchain-openai>=1.0.0
langchain-community>=0.0.20
duckduckgo-search>=4.0.0
aiosqlite>=0.19.0
pydantic>=2.0.0
```

## 10. 开发计划

### Phase 1: 后端核心

- [ ] FastAPI 项目初始化
- [ ] WebSocket 端点
- [ ] DeepAgents 集成
- [ ] SQLite 会话管理
- [ ] 自定义工具实现

### Phase 2: 前端基础

- [ ] React 项目初始化
- [ ] WebSocket 客户端
- [ ] Chatbot 界面
- [ ] 思考过程开关

### Phase 3: 完善功能

- [ ] 流式输出美化
- [ ] 历史记录
- [ ] 错误处理
- [ ] 加载状态

---

*最后更新: 2026-05-23*
*作者: 夜小白科技有限公司*